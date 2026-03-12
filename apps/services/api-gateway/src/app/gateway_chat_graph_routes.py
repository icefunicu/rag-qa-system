from __future__ import annotations

from typing import Any
from uuid import uuid4

import httpx
from fastapi import APIRouter, HTTPException, Request

from shared.auth import CurrentUser
from shared.inflight_limiter import InflightLimiter

from .db import to_json
from .gateway_audit_support import require_permission, write_gateway_audit_event
from .gateway_graph import GatewayGraphDependencies, load_interrupt_for_run, resume_gateway_graph_turn, run_gateway_graph_turn
from .gateway_idempotency import begin_gateway_idempotency, complete_gateway_idempotency, fail_gateway_idempotency
from .gateway_runtime import CHAT_PERMISSION, gateway_db, runtime_settings
from .gateway_schemas import CreateRunRequest, CreateThreadRequest, SubmitInterruptRequest
from .gateway_scope import default_scope, fetch_corpora, fetch_corpus_documents, normalize_execution_mode, resolve_scope_snapshot
from .gateway_sessions import list_session_messages, load_session_for_user, persist_chat_turn, recent_history_messages


router = APIRouter()
CHAT_GRAPH_INFLIGHT_LIMITER = InflightLimiter("gateway_chat_v2")


def _scope_payload_dict(scope: Any | None) -> dict[str, Any] | None:
    if scope is None:
        return None
    payload = scope.model_dump() if hasattr(scope, "model_dump") else dict(scope)
    if not payload.get("agent_profile_id"):
        payload.pop("agent_profile_id", None)
    if not payload.get("prompt_template_id"):
        payload.pop("prompt_template_id", None)
    return payload


def _thread_payload(session_row: dict[str, Any]) -> dict[str, Any]:
    scope_json = dict(session_row.get("scope_json") or {})
    return {
        "id": str(session_row.get("id") or ""),
        "thread_id": str(session_row.get("id") or ""),
        "title": str(session_row.get("title") or ""),
        "scope": scope_json,
        "execution_mode": str(scope_json.get("execution_mode") or "grounded"),
        "created_at": session_row.get("created_at"),
        "updated_at": session_row.get("updated_at"),
    }


def _graph_dependencies() -> GatewayGraphDependencies:
    async def resolve_scope(current_user: CurrentUser, scope_payload):
        async def fetch_corpora_fn(user: CurrentUser, *, include_counts: bool):
            return await fetch_corpora(user, include_counts=include_counts, kb_service_url=runtime_settings.kb_service_url)

        async def fetch_corpus_documents_fn(client: httpx.AsyncClient, *, user: CurrentUser, corpus_id: str):
            return await fetch_corpus_documents(client, user=user, corpus_id=corpus_id, kb_service_url=runtime_settings.kb_service_url)

        return await resolve_scope_snapshot(
            current_user,
            scope_payload,
            fetch_corpora_fn=fetch_corpora_fn,
            fetch_corpus_documents_fn=fetch_corpus_documents_fn,
        )

    async def retrieve_scope(**kwargs):
        from .gateway_retrieval import retrieve_scope_evidence

        async def fetch_docs(client: httpx.AsyncClient, *, user: CurrentUser, corpus_id: str):
            return await fetch_corpus_documents(client, user=user, corpus_id=corpus_id, kb_service_url=runtime_settings.kb_service_url)

        return await retrieve_scope_evidence(
            fetch_corpus_documents_fn=fetch_docs,
            kb_service_url=runtime_settings.kb_service_url,
            **kwargs,
        )

    async def fetch_docs(client: httpx.AsyncClient, *, user: CurrentUser, corpus_id: str):
        return await fetch_corpus_documents(client, user=user, corpus_id=corpus_id, kb_service_url=runtime_settings.kb_service_url)

    return GatewayGraphDependencies(
        load_session_fn=lambda sid, actor: load_session_for_user(sid, actor, default_scope_fn=default_scope),
        default_scope_fn=default_scope,
        resolve_scope_snapshot_fn=resolve_scope,
        recent_history_messages_fn=lambda sid, actor, limit=8: recent_history_messages(
            sid,
            actor,
            load_session_fn=lambda session_id, current_user: load_session_for_user(session_id, current_user, default_scope_fn=default_scope),
            limit=limit,
        ),
        retrieve_scope_evidence_fn=retrieve_scope,
        fetch_corpus_documents_fn=fetch_docs,
        persist_chat_turn_fn=persist_chat_turn,
    )


def _acquire_or_raise(*, request: Request, user: CurrentUser, endpoint: str):
    decision = CHAT_GRAPH_INFLIGHT_LIMITER.acquire(
        user_key=str(user.user_id),
        global_limit=runtime_settings.chat_max_in_flight_global,
        per_user_limit=runtime_settings.chat_max_in_flight_per_user,
    )
    if decision.allowed:
        return decision
    write_gateway_audit_event(
        action=endpoint,
        outcome="throttled",
        request=request,
        user=user,
        resource_type="chat_thread",
        scope="owner",
        details={"backpressure_scope": decision.scope},
    )
    raise HTTPException(
        status_code=429,
        detail={"detail": "too many in-flight requests", "code": "too_many_inflight_requests"},
        headers={"Retry-After": "1"},
    )


@router.post("/api/v2/chat/threads")
async def create_chat_thread(payload: CreateThreadRequest, request: Request, user: CurrentUser) -> dict[str, Any]:
    require_permission(request, user, CHAT_PERMISSION, action="chat.v2.thread.create", resource_type="chat_thread")
    scope_snapshot = await resolve_scope_snapshot(
        user,
        payload.scope,
        fetch_corpora_fn=lambda current_user, include_counts=False: fetch_corpora(
            current_user,
            include_counts=include_counts,
            kb_service_url=runtime_settings.kb_service_url,
        ),
        fetch_corpus_documents_fn=lambda client, **kwargs: fetch_corpus_documents(
            client,
            kb_service_url=runtime_settings.kb_service_url,
            **kwargs,
        ),
    )
    scope_snapshot["execution_mode"] = normalize_execution_mode(payload.execution_mode, default="grounded")
    thread_id = str(uuid4())
    with gateway_db.connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO chat_sessions (id, user_id, title, scope_json) VALUES (%s, %s, %s, %s::jsonb)",
                (thread_id, user.user_id, payload.title.strip(), to_json(scope_snapshot)),
            )
        conn.commit()
    thread = _thread_payload(load_session_for_user(thread_id, user, default_scope_fn=default_scope))
    write_gateway_audit_event(
        action="chat.v2.thread.create",
        outcome="success",
        request=request,
        user=user,
        resource_type="chat_thread",
        resource_id=thread_id,
        scope="owner",
        details={"execution_mode": thread["execution_mode"]},
    )
    return {"thread": thread}


@router.get("/api/v2/chat/threads/{thread_id}")
async def get_chat_thread(thread_id: str, request: Request, user: CurrentUser) -> dict[str, Any]:
    require_permission(request, user, CHAT_PERMISSION, action="chat.v2.thread.get", resource_type="chat_thread", resource_id=thread_id)
    return {"thread": _thread_payload(load_session_for_user(thread_id, user, default_scope_fn=default_scope))}


@router.get("/api/v2/chat/threads/{thread_id}/messages")
async def list_chat_thread_messages(thread_id: str, request: Request, user: CurrentUser) -> dict[str, Any]:
    require_permission(request, user, CHAT_PERMISSION, action="chat.v2.thread.messages.list", resource_type="chat_thread", resource_id=thread_id)
    return {
        "items": list_session_messages(
            thread_id,
            user,
            load_session_fn=lambda sid, current_user: load_session_for_user(sid, current_user, default_scope_fn=default_scope),
        )
    }


@router.post("/api/v2/chat/threads/{thread_id}/runs")
async def create_chat_run(thread_id: str, payload: CreateRunRequest, request: Request, user: CurrentUser) -> dict[str, Any]:
    require_permission(request, user, CHAT_PERMISSION, action="chat.v2.run.create", resource_type="chat_thread", resource_id=thread_id)
    state = begin_gateway_idempotency(
        request,
        user,
        request_scope="chat.v2.run.create",
        payload={
            "thread_id": thread_id,
            "question": payload.question.strip(),
            "scope": _scope_payload_dict(payload.scope),
            "execution_mode": payload.execution_mode,
        },
    )
    if state.replay_payload is not None:
        return state.replay_payload
    decision = _acquire_or_raise(request=request, user=user, endpoint="chat.v2.run.create")
    try:
        result = await run_gateway_graph_turn(
            session_id=thread_id,
            payload=payload.model_dump(),
            request_scope="chat.v2.run.create",
            user=user,
            request_path=str(request.url.path),
            deps=_graph_dependencies(),
        )
    except Exception as exc:
        fail_gateway_idempotency(state, user, exc)
        raise
    finally:
        CHAT_GRAPH_INFLIGHT_LIMITER.release(decision.ticket)
    complete_gateway_idempotency(
        state,
        user,
        response_payload=result,
        resource_id=str(((result.get("run") or {}) if isinstance(result, dict) else {}).get("id") or thread_id),
    )
    return result


@router.get("/api/v2/chat/runs/{run_id}")
async def get_chat_run(run_id: str, request: Request, user: CurrentUser) -> dict[str, Any]:
    require_permission(request, user, CHAT_PERMISSION, action="chat.v2.run.get", resource_type="chat_run", resource_id=run_id)
    run = load_workflow_run_for_user(run_id, user)
    interrupt = load_interrupt_for_run(interrupt_id=str(run.get("interrupt_id") or ""), user=user) if str(run.get("interrupt_id") or "") else {}
    return {"run": run, "interrupt": interrupt}


@router.post("/api/v2/chat/runs/{run_id}/resume")
async def resume_chat_run(run_id: str, payload: SubmitInterruptRequest, request: Request, user: CurrentUser) -> dict[str, Any]:
    require_permission(request, user, CHAT_PERMISSION, action="chat.v2.run.resume", resource_type="chat_run", resource_id=run_id)
    run = load_workflow_run_for_user(run_id, user)
    interrupt_id = str(run.get("interrupt_id") or "")
    if not interrupt_id:
        raise HTTPException(status_code=409, detail={"detail": "run has no pending interrupt", "code": "chat_run_not_interrupted"})
    state = begin_gateway_idempotency(
        request,
        user,
        request_scope="chat.v2.run.resume",
        payload={"run_id": run_id, **payload.model_dump()},
    )
    if state.replay_payload is not None:
        return state.replay_payload
    decision = _acquire_or_raise(request=request, user=user, endpoint="chat.v2.run.resume")
    try:
        result = await resume_gateway_graph_turn(
            run_id=run_id,
            user=user,
            response_payload=payload.model_dump(exclude_none=True),
            deps=_graph_dependencies(),
            interrupt_id=interrupt_id,
        )
    except Exception as exc:
        fail_gateway_idempotency(state, user, exc)
        raise
    finally:
        CHAT_GRAPH_INFLIGHT_LIMITER.release(decision.ticket)
    complete_gateway_idempotency(state, user, response_payload=result, resource_id=run_id)
    return result


@router.post("/api/v2/chat/interrupts/{interrupt_id}/submit")
async def submit_chat_interrupt(interrupt_id: str, payload: SubmitInterruptRequest, request: Request, user: CurrentUser) -> dict[str, Any]:
    require_permission(request, user, CHAT_PERMISSION, action="chat.v2.interrupt.submit", resource_type="chat_interrupt", resource_id=interrupt_id)
    interrupt_row = load_interrupt_for_run(interrupt_id=interrupt_id, user=user)
    if str(interrupt_row.get("status") or "") != "pending":
        raise HTTPException(status_code=409, detail={"detail": "interrupt is not pending", "code": "chat_interrupt_conflict"})
    return await resume_chat_run(str(interrupt_row.get("run_id") or ""), payload, request, user)
