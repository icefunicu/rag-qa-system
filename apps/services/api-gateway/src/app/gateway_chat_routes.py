from __future__ import annotations

import asyncio
import time
from typing import Any
from uuid import uuid4

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from shared.auth import CurrentUser
from shared.inflight_limiter import InflightLimiter
from shared.sse import encode_sse_event

from .db import to_json
from .gateway_answering import stream_grounded_answer
from .gateway_audit_support import require_permission, write_gateway_audit_event
from .gateway_chat_service import (
    build_chat_response_payload,
    finalize_chat_message,
    handle_chat_message,
    prepare_chat_message,
)
from .gateway_idempotency import begin_gateway_idempotency, complete_gateway_idempotency, fail_gateway_idempotency
from .gateway_retrieval import retrieve_scope_evidence
from .gateway_runtime import CHAT_PERMISSION, GATEWAY_BACKPRESSURE_TOTAL, GATEWAY_CHAT_REQUESTS_TOTAL, gateway_db, runtime_settings
from .gateway_schemas import CreateSessionRequest, SendMessageRequest, UpdateSessionRequest
from .gateway_scope import default_scope, fetch_corpora, fetch_corpus_documents, normalize_execution_mode, resolve_scope_snapshot
from .gateway_sessions import list_session_messages, load_session_for_user, persist_chat_turn, recent_history_messages


router = APIRouter()
CHAT_INFLIGHT_LIMITER = InflightLimiter("gateway_chat")


def _reject_backpressure(*, request: Request, user: CurrentUser, endpoint: str, scope: str) -> None:
    GATEWAY_BACKPRESSURE_TOTAL.labels(scope, endpoint).inc()
    write_gateway_audit_event(
        action=endpoint,
        outcome="throttled",
        request=request,
        user=user,
        resource_type="chat_session",
        scope="owner",
        details={"backpressure_scope": scope},
    )
    raise HTTPException(
        status_code=429,
        detail={"detail": "too many in-flight requests", "code": "too_many_inflight_requests"},
        headers={"Retry-After": "1"},
    )


def _fetch_corpora(current_user: CurrentUser, *, include_counts: bool):
    return fetch_corpora(current_user, include_counts=include_counts, kb_service_url=runtime_settings.kb_service_url)


def _fetch_corpus_documents(client: httpx.AsyncClient, *, user: CurrentUser, corpus_id: str):
    return fetch_corpus_documents(client, user=user, corpus_id=corpus_id, kb_service_url=runtime_settings.kb_service_url)


async def _resolve_scope_snapshot(user: CurrentUser, scope_payload):
    return await resolve_scope_snapshot(
        user,
        scope_payload,
        fetch_corpora_fn=_fetch_corpora,
        fetch_corpus_documents_fn=_fetch_corpus_documents,
    )


async def _retrieve_scope_evidence(**kwargs):
    return await retrieve_scope_evidence(
        fetch_corpus_documents_fn=_fetch_corpus_documents,
        kb_service_url=runtime_settings.kb_service_url,
        **kwargs,
    )


@router.get("/api/v1/chat/corpora")
async def list_chat_corpora(request: Request, user: CurrentUser) -> dict[str, Any]:
    require_permission(request, user, CHAT_PERMISSION, action="chat.corpora.list", resource_type="chat_scope")
    return {"items": await fetch_corpora(user, include_counts=True, kb_service_url=runtime_settings.kb_service_url)}


@router.get("/api/v1/chat/corpora/{corpus_id}/documents")
async def list_chat_corpus_documents(corpus_id: str, request: Request, user: CurrentUser) -> dict[str, Any]:
    require_permission(request, user, CHAT_PERMISSION, action="chat.corpus_documents.list", resource_type="chat_scope", resource_id=corpus_id)
    timeout = httpx.Timeout(runtime_settings.request_timeout_seconds)
    async with httpx.AsyncClient(timeout=timeout) as client:
        items = await fetch_corpus_documents(client, user=user, corpus_id=corpus_id, kb_service_url=runtime_settings.kb_service_url)
    return {"items": items}


@router.post("/api/v1/chat/sessions")
async def create_chat_session(payload: CreateSessionRequest, request: Request, user: CurrentUser) -> dict[str, Any]:
    require_permission(request, user, CHAT_PERMISSION, action="chat.session.create", resource_type="chat_session")
    scope_snapshot = await _resolve_scope_snapshot(user, payload.scope)
    scope_snapshot["execution_mode"] = normalize_execution_mode(payload.execution_mode, default="grounded")
    session_id = str(uuid4())
    with gateway_db.connect() as conn:
        with conn.cursor() as cur:
            cur.execute("INSERT INTO chat_sessions (id, user_id, title, scope_json) VALUES (%s, %s, %s, %s::jsonb)", (session_id, user.user_id, payload.title.strip(), to_json(scope_snapshot)))
        conn.commit()
    write_gateway_audit_event(action="chat.session.create", outcome="success", request=request, user=user, resource_type="chat_session", resource_id=session_id, scope="owner", details={"mode": scope_snapshot.get("mode", "all")})
    return {"session_id": session_id, "session": load_session_for_user(session_id, user, default_scope_fn=default_scope)}


@router.get("/api/v1/chat/sessions")
async def list_chat_sessions(request: Request, user: CurrentUser) -> dict[str, Any]:
    require_permission(request, user, CHAT_PERMISSION, action="chat.session.list", resource_type="chat_session")
    with gateway_db.connect() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM chat_sessions WHERE user_id = %s ORDER BY updated_at DESC", (user.user_id,))
            rows = cur.fetchall()
    return {"items": rows}


@router.get("/api/v1/chat/sessions/{session_id}")
async def get_chat_session(session_id: str, request: Request, user: CurrentUser) -> dict[str, Any]:
    require_permission(request, user, CHAT_PERMISSION, action="chat.session.get", resource_type="chat_session", resource_id=session_id)
    return load_session_for_user(session_id, user, default_scope_fn=default_scope)


@router.patch("/api/v1/chat/sessions/{session_id}")
async def update_chat_session(session_id: str, payload: UpdateSessionRequest, request: Request, user: CurrentUser) -> dict[str, Any]:
    require_permission(request, user, CHAT_PERMISSION, action="chat.session.update", resource_type="chat_session", resource_id=session_id)
    current = load_session_for_user(session_id, user, default_scope_fn=default_scope)
    next_scope = dict(current.get("scope_json") or default_scope())
    if payload.scope is not None:
        next_scope = await _resolve_scope_snapshot(user, payload.scope)
    next_scope["execution_mode"] = normalize_execution_mode(
        payload.execution_mode or str(next_scope.get("execution_mode") or ""),
        default="grounded",
    )
    next_title = payload.title.strip() if payload.title is not None else str(current.get("title") or "")
    with gateway_db.connect() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE chat_sessions SET title = %s, scope_json = %s::jsonb, updated_at = NOW() WHERE id = %s AND user_id = %s", (next_title, to_json(next_scope), session_id, user.user_id))
        conn.commit()
    write_gateway_audit_event(action="chat.session.update", outcome="success", request=request, user=user, resource_type="chat_session", resource_id=session_id, scope="owner", details={"mode": next_scope.get("mode", "all")})
    return {"session": load_session_for_user(session_id, user, default_scope_fn=default_scope)}


@router.delete("/api/v1/chat/sessions/{session_id}")
async def delete_chat_session(session_id: str, request: Request, user: CurrentUser) -> dict[str, Any]:
    require_permission(request, user, CHAT_PERMISSION, action="chat.session.delete", resource_type="chat_session", resource_id=session_id)
    load_session_for_user(session_id, user, default_scope_fn=default_scope)
    with gateway_db.connect() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM chat_sessions WHERE id = %s AND user_id = %s", (session_id, user.user_id))
        conn.commit()
    write_gateway_audit_event(action="chat.session.delete", outcome="success", request=request, user=user, resource_type="chat_session", resource_id=session_id, scope="owner")
    return {"deleted": True, "session_id": session_id}


@router.get("/api/v1/chat/sessions/{session_id}/messages")
async def list_chat_messages(session_id: str, request: Request, user: CurrentUser) -> dict[str, Any]:
    require_permission(request, user, CHAT_PERMISSION, action="chat.message.list", resource_type="chat_session", resource_id=session_id)
    return {"items": list_session_messages(session_id, user, load_session_fn=lambda sid, current_user: load_session_for_user(sid, current_user, default_scope_fn=default_scope))}


@router.post("/api/v1/chat/sessions/{session_id}/messages")
async def send_chat_message(session_id: str, payload: SendMessageRequest, request: Request, user: CurrentUser) -> dict[str, Any]:
    require_permission(request, user, CHAT_PERMISSION, action="chat.message.send", resource_type="chat_session", resource_id=session_id)
    state = begin_gateway_idempotency(
        request,
        user,
        request_scope="chat.message.send",
        payload={
            "session_id": session_id,
            "question": payload.question.strip(),
            "scope": payload.scope.model_dump() if payload.scope is not None else None,
            "execution_mode": payload.execution_mode,
        },
    )
    if state.replay_payload is not None:
        return state.replay_payload
    decision = CHAT_INFLIGHT_LIMITER.acquire(
        user_key=str(user.user_id),
        global_limit=runtime_settings.chat_max_in_flight_global,
        per_user_limit=runtime_settings.chat_max_in_flight_per_user,
    )
    if not decision.allowed:
        _reject_backpressure(request=request, user=user, endpoint="chat.message.send", scope=decision.scope)
    try:
        result = await handle_chat_message(
            session_id=session_id,
            payload=payload,
            request=request,
            user=user,
            load_session_fn=lambda sid, current_user: load_session_for_user(sid, current_user, default_scope_fn=default_scope),
            default_scope_fn=default_scope,
            resolve_scope_snapshot_fn=_resolve_scope_snapshot,
            recent_history_messages_fn=lambda sid, current_user, limit=8: recent_history_messages(sid, current_user, load_session_fn=lambda session, actor: load_session_for_user(session, actor, default_scope_fn=default_scope), limit=limit),
            retrieve_scope_evidence_fn=_retrieve_scope_evidence,
            fetch_corpus_documents_fn=_fetch_corpus_documents,
            persist_chat_turn_fn=persist_chat_turn,
        )
    except Exception as exc:
        fail_gateway_idempotency(state, user, exc)
        GATEWAY_CHAT_REQUESTS_TOTAL.labels("error", "error").inc()
        raise
    finally:
        CHAT_INFLIGHT_LIMITER.release(decision.ticket)
    complete_gateway_idempotency(state, user, response_payload=result, resource_id=str(((result.get("message") or {}) if isinstance(result, dict) else {}).get("id") or session_id))
    return result


@router.post("/api/v1/chat/sessions/{session_id}/messages/stream")
async def stream_chat_message(session_id: str, payload: SendMessageRequest, request: Request, user: CurrentUser) -> StreamingResponse:
    require_permission(request, user, CHAT_PERMISSION, action="chat.message.stream", resource_type="chat_session", resource_id=session_id)
    state = begin_gateway_idempotency(
        request,
        user,
        request_scope="chat.message.stream",
        payload={
            "session_id": session_id,
            "question": payload.question.strip(),
            "scope": payload.scope.model_dump() if payload.scope is not None else None,
            "execution_mode": payload.execution_mode,
        },
    )
    if state.replay_payload is not None:
        result = state.replay_payload
        def replay_generate() -> Any:
            yield encode_sse_event(
                "metadata",
                {
                    "strategy_used": result.get("strategy_used", ""),
                    "execution_mode": result.get("execution_mode", "grounded"),
                    "answer_mode": result.get("answer_mode", ""),
                    "evidence_status": result.get("evidence_status", ""),
                    "grounding_score": result.get("grounding_score", 0),
                    "refusal_reason": result.get("refusal_reason", ""),
                    "safety": result.get("safety", {}),
                    "retrieval": result.get("retrieval", {}),
                },
            )
            for citation in result.get("citations", []) or []:
                yield encode_sse_event("citation", citation)
            yield encode_sse_event(
                "answer",
                {
                    "answer": result.get("answer", ""),
                    "grounding_score": result.get("grounding_score", 0),
                    "refusal_reason": result.get("refusal_reason", ""),
                },
            )
            yield encode_sse_event("message", (result.get("message") or {}) if isinstance(result, dict) else {})
            yield encode_sse_event("done", {"session_id": session_id})

        return StreamingResponse(replay_generate(), media_type="text/event-stream")
    decision = CHAT_INFLIGHT_LIMITER.acquire(
        user_key=str(user.user_id),
        global_limit=runtime_settings.chat_max_in_flight_global,
        per_user_limit=runtime_settings.chat_max_in_flight_per_user,
    )
    if not decision.allowed:
        _reject_backpressure(request=request, user=user, endpoint="chat.message.stream", scope=decision.scope)

    async def generate() -> Any:
        try:
            prepared = await prepare_chat_message(
                session_id=session_id,
                payload=payload,
                user=user,
                load_session_fn=lambda sid, current_user: load_session_for_user(sid, current_user, default_scope_fn=default_scope),
                default_scope_fn=default_scope,
                resolve_scope_snapshot_fn=_resolve_scope_snapshot,
                recent_history_messages_fn=lambda sid, current_user, limit=8: recent_history_messages(sid, current_user, load_session_fn=lambda session, actor: load_session_for_user(session, actor, default_scope_fn=default_scope), limit=limit),
                retrieve_scope_evidence_fn=_retrieve_scope_evidence,
                fetch_corpus_documents_fn=_fetch_corpus_documents,
            )
            yield encode_sse_event(
                "metadata",
                {
                    "strategy_used": "agent_grounded_qa"
                    if prepared["execution_mode"] == "agent"
                    else "common_knowledge_chat"
                    if prepared["answer_mode"] == "common_knowledge"
                    else "hybrid_grounded_qa",
                    "execution_mode": prepared["execution_mode"],
                    "answer_mode": prepared["answer_mode"],
                    "evidence_status": prepared["evidence_status"],
                    "grounding_score": prepared["grounding_score"],
                    "refusal_reason": prepared["refusal_reason"],
                    "safety": prepared["safety"],
                    "retrieval": prepared["retrieval_meta"],
                },
            )
            for citation in prepared["evidence"]:
                yield encode_sse_event("citation", citation)

            generation_started = time.perf_counter()
            latest_answer = ""
            answer_queue: asyncio.Queue[str | None] = asyncio.Queue()

            async def emit_answer(answer_text: str) -> None:
                nonlocal latest_answer
                latest_answer = answer_text
                await answer_queue.put(
                    encode_sse_event(
                        "answer",
                        {
                            "answer": answer_text,
                            "grounding_score": prepared["grounding_score"],
                            "refusal_reason": prepared["refusal_reason"],
                        },
                    )
                )

            async def run_answer_stream() -> dict[str, Any]:
                try:
                    return await stream_grounded_answer(
                        question=prepared["contextualized_question"],
                        history=prepared["history"],
                        evidence=prepared["evidence"],
                        answer_mode=prepared["answer_mode"],
                        on_answer=emit_answer,
                        safety=prepared["safety"],
                    )
                finally:
                    await answer_queue.put(None)

            answer_task = asyncio.create_task(run_answer_stream())
            while True:
                chunk = await answer_queue.get()
                if chunk is None:
                    break
                yield chunk
            answer_payload = await answer_task
            generation_ms = round((time.perf_counter() - generation_started) * 1000.0, 3)
            response_payload = build_chat_response_payload(
                prepared=prepared,
                answer_payload=answer_payload,
                generation_ms=generation_ms,
            )
            result = finalize_chat_message(
                prepared=prepared,
                request=request,
                user=user,
                response_payload=response_payload,
                persist_chat_turn_fn=persist_chat_turn,
            )
            complete_gateway_idempotency(state, user, response_payload=result, resource_id=str(((result.get("message") or {}) if isinstance(result, dict) else {}).get("id") or session_id))
            final_message = (result.get("message") or {}) if isinstance(result, dict) else {}
            if str(final_message.get("content") or "") and str(final_message.get("content") or "") != latest_answer:
                yield encode_sse_event(
                    "answer",
                    {
                        "answer": str(final_message.get("content") or ""),
                        "grounding_score": prepared["grounding_score"],
                        "refusal_reason": prepared["refusal_reason"],
                    },
                )
            yield encode_sse_event("message", final_message)
            yield encode_sse_event("done", {"session_id": session_id, "trace_id": prepared["trace_id"]})
        except Exception as exc:
            fail_gateway_idempotency(state, user, exc)
            GATEWAY_CHAT_REQUESTS_TOTAL.labels("error", "error").inc()
            yield encode_sse_event(
                "error",
                {"detail": str(getattr(exc, "detail", "") or "stream chat failed")},
            )
        finally:
            CHAT_INFLIGHT_LIMITER.release(decision.ticket)

    return StreamingResponse(generate(), media_type="text/event-stream")
