from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from shared.auth import CurrentUser
from shared.inflight_limiter import InflightLimiter
from shared.sse import encode_sse_event
from shared.tracing import current_trace_id

from .kb_api_support import audit_event, require_kb_permission
from .kb_query_helpers import build_query_response, prepare_query_response, serialize_evidence, stream_query_response
from .kb_resource_store import ensure_base_exists
from .kb_runtime import (
    CHAT_PERMISSION,
    KB_BACKPRESSURE_TOTAL,
    KB_QUERY_MAX_IN_FLIGHT_GLOBAL,
    KB_QUERY_MAX_IN_FLIGHT_PER_USER,
    KB_READ_PERMISSION,
    KB_RETRIEVE_LATENCY_MS,
    KB_RETRIEVE_REQUESTS_TOTAL,
    KB_SAFETY_EVENTS_TOTAL,
)
from .kb_schemas import KBQueryRequest, RetrievalDebugRequest, RetrieveRequest
from .retrieve import retrieve_kb_result, run_retrieval_graph


router = APIRouter()
KB_QUERY_INFLIGHT_LIMITER = InflightLimiter("kb_query")


def _reject_backpressure(*, request: Request, user: CurrentUser, endpoint: str, base_id: str, scope: str) -> None:
    KB_BACKPRESSURE_TOTAL.labels(scope, endpoint).inc()
    audit_event(
        action=endpoint,
        outcome="throttled",
        request=request,
        user=user,
        resource_type="knowledge_base",
        resource_id=base_id,
        scope="owner",
        details={"backpressure_scope": scope},
    )
    raise HTTPException(
        status_code=429,
        detail={"detail": "too many in-flight requests", "code": "too_many_inflight_requests"},
        headers={"Retry-After": "1"},
    )


def _graph_meta(*, entrypoint: str, final_node: str) -> dict[str, Any]:
    return {
        "engine": "langgraph",
        "entrypoint": entrypoint,
        "final_node": final_node,
        "trace_id": current_trace_id(),
    }


@router.post("/api/v1/kb/retrieve")
def retrieve_kb(payload: RetrieveRequest, request: Request, user: CurrentUser) -> dict[str, Any]:
    require_kb_permission(request, user, KB_READ_PERMISSION, action="kb.retrieve", resource_type="knowledge_base", resource_id=payload.base_id)
    ensure_base_exists(payload.base_id, user=user, request=request, action="kb.retrieve")
    result = retrieve_kb_result(
        base_id=payload.base_id,
        question=payload.question,
        document_ids=payload.document_ids,
        limit=payload.limit,
    )
    degraded = "true" if result.stats.degraded_signals else "false"
    KB_RETRIEVE_REQUESTS_TOTAL.labels("success", degraded).inc()
    KB_RETRIEVE_LATENCY_MS.observe(float(result.stats.retrieval_ms))
    return {
        "items": [serialize_evidence(item, corpus_id=f"kb:{payload.base_id}") for item in result.items],
        "retrieval": result.stats.as_dict(),
        "trace_id": current_trace_id(),
    }


@router.post("/api/v2/kb/retrieve")
def retrieve_kb_v2(payload: RetrieveRequest, request: Request, user: CurrentUser) -> dict[str, Any]:
    require_kb_permission(request, user, KB_READ_PERMISSION, action="kb.v2.retrieve", resource_type="knowledge_base", resource_id=payload.base_id)
    ensure_base_exists(payload.base_id, user=user, request=request, action="kb.v2.retrieve")
    graph_state = run_retrieval_graph(
        {
            "base_id": payload.base_id,
            "question": payload.question,
            "document_ids": payload.document_ids,
            "limit": payload.limit,
        }
    )
    result = graph_state["result"]
    degraded = "true" if result.stats.degraded_signals else "false"
    KB_RETRIEVE_REQUESTS_TOTAL.labels("success", degraded).inc()
    KB_RETRIEVE_LATENCY_MS.observe(float(result.stats.retrieval_ms))
    return {
        "items": [serialize_evidence(item, corpus_id=f"kb:{payload.base_id}") for item in result.items],
        "retrieval": result.stats.as_dict(),
        "trace_id": current_trace_id(),
        "graph": _graph_meta(entrypoint="prepare_request", final_node="fuse_and_rerank"),
    }


@router.post("/api/v1/kb/retrieve/debug")
def retrieve_kb_debug(payload: RetrievalDebugRequest, request: Request, user: CurrentUser) -> dict[str, Any]:
    require_kb_permission(
        request,
        user,
        KB_READ_PERMISSION,
        action="kb.retrieve.debug",
        resource_type="knowledge_base",
        resource_id=payload.base_id,
    )
    ensure_base_exists(payload.base_id, user=user, request=request, action="kb.retrieve.debug")
    result = retrieve_kb_result(
        base_id=payload.base_id,
        question=payload.question,
        document_ids=payload.document_ids,
        limit=payload.limit,
    )
    items = []
    for rank, item in enumerate(result.items, start=1):
        payload_item = serialize_evidence(item, corpus_id=f"kb:{payload.base_id}")
        payload_item["debug"] = {
            "rank": rank,
            "score": float(((payload_item.get("evidence_path") or {}).get("final_score") or 0.0)),
            "signal_scores": dict(payload_item.get("signal_scores") or {}),
            "rerank_score": float(((payload_item.get("signal_scores") or {}).get("rerank") or 0.0)),
        }
        items.append(payload_item)
    degraded = "true" if result.stats.degraded_signals else "false"
    KB_RETRIEVE_REQUESTS_TOTAL.labels("success", degraded).inc()
    KB_RETRIEVE_LATENCY_MS.observe(float(result.stats.retrieval_ms))
    return {
        "query": payload.question,
        "items": items,
        "retrieval": result.stats.as_dict(),
        "trace_id": current_trace_id(),
    }


@router.post("/api/v1/kb/query")
async def query_kb(payload: KBQueryRequest, request: Request, user: CurrentUser) -> dict[str, Any]:
    require_kb_permission(request, user, KB_READ_PERMISSION, action="kb.query", resource_type="knowledge_base", resource_id=payload.base_id)
    require_kb_permission(request, user, CHAT_PERMISSION, action="kb.query", resource_type="knowledge_base", resource_id=payload.base_id)
    ensure_base_exists(payload.base_id, user=user, request=request, action="kb.query")
    decision = KB_QUERY_INFLIGHT_LIMITER.acquire(
        user_key=str(user.user_id),
        global_limit=KB_QUERY_MAX_IN_FLIGHT_GLOBAL,
        per_user_limit=KB_QUERY_MAX_IN_FLIGHT_PER_USER,
    )
    if not decision.allowed:
        _reject_backpressure(request=request, user=user, endpoint="kb.query", base_id=payload.base_id, scope=decision.scope)
    try:
        result = await build_query_response(base_id=payload.base_id, question=payload.question, document_ids=payload.document_ids)
    finally:
        KB_QUERY_INFLIGHT_LIMITER.release(decision.ticket)
    degraded = "true" if list((result.get("retrieval") or {}).get("degraded_signals") or []) else "false"
    result_label = "refusal" if str(result.get("answer_mode") or "") == "refusal" else "success"
    KB_RETRIEVE_REQUESTS_TOTAL.labels(result_label, degraded).inc()
    KB_RETRIEVE_LATENCY_MS.observe(float((result.get("retrieval") or {}).get("retrieval_ms") or 0.0))
    safety = dict(result.get("safety") or {})
    if str(safety.get("risk_level") or "") in {"medium", "high"}:
        KB_SAFETY_EVENTS_TOTAL.labels(str(safety.get("risk_level") or "low"), str(safety.get("action") or "allow")).inc()
    if bool(safety.get("blocked")):
        audit_event(
            action="kb.query",
            outcome="blocked",
            request=request,
            user=user,
            resource_type="knowledge_base",
            resource_id=payload.base_id,
            scope="owner",
            details={
                "safety_risk_level": str(safety.get("risk_level") or "low"),
                "safety_reason_codes": list(safety.get("reason_codes") or []),
            },
        )
    return result


@router.post("/api/v2/kb/query")
async def query_kb_v2(payload: KBQueryRequest, request: Request, user: CurrentUser) -> dict[str, Any]:
    result = await query_kb(payload, request, user)
    result["graph"] = _graph_meta(entrypoint="prepare_query_response", final_node="finalize_query_response")
    return result


@router.post("/api/v1/kb/query/stream")
async def stream_query_kb(payload: KBQueryRequest, request: Request, user: CurrentUser) -> StreamingResponse:
    require_kb_permission(request, user, KB_READ_PERMISSION, action="kb.query.stream", resource_type="knowledge_base", resource_id=payload.base_id)
    require_kb_permission(request, user, CHAT_PERMISSION, action="kb.query.stream", resource_type="knowledge_base", resource_id=payload.base_id)
    ensure_base_exists(payload.base_id, user=user, request=request, action="kb.query.stream")
    decision = KB_QUERY_INFLIGHT_LIMITER.acquire(
        user_key=str(user.user_id),
        global_limit=KB_QUERY_MAX_IN_FLIGHT_GLOBAL,
        per_user_limit=KB_QUERY_MAX_IN_FLIGHT_PER_USER,
    )
    if not decision.allowed:
        _reject_backpressure(request=request, user=user, endpoint="kb.query.stream", base_id=payload.base_id, scope=decision.scope)
    prepared = prepare_query_response(base_id=payload.base_id, question=payload.question, document_ids=payload.document_ids)
    degraded = "true" if list((prepared.get("retrieval") or {}).get("degraded_signals") or []) else "false"
    result_label = "refusal" if str(prepared.get("answer_mode") or "") == "refusal" else "success"
    KB_RETRIEVE_REQUESTS_TOTAL.labels(result_label, degraded).inc()
    KB_RETRIEVE_LATENCY_MS.observe(float((prepared.get("retrieval") or {}).get("retrieval_ms") or 0.0))
    safety = dict(prepared.get("safety") or {})
    if str(safety.get("risk_level") or "") in {"medium", "high"}:
        KB_SAFETY_EVENTS_TOTAL.labels(str(safety.get("risk_level") or "low"), str(safety.get("action") or "allow")).inc()
    if bool(safety.get("blocked")):
        audit_event(
            action="kb.query.stream",
            outcome="blocked",
            request=request,
            user=user,
            resource_type="knowledge_base",
            resource_id=payload.base_id,
            scope="owner",
            details={
                "safety_risk_level": str(safety.get("risk_level") or "low"),
                "safety_reason_codes": list(safety.get("reason_codes") or []),
            },
        )

    async def generate() -> Any:
        try:
            yield encode_sse_event(
                "metadata",
                {
                    "strategy_used": prepared.get("strategy_used", ""),
                    "answer_mode": prepared.get("answer_mode", ""),
                    "evidence_status": prepared.get("evidence_status", ""),
                    "grounding_score": prepared.get("grounding_score", 0),
                    "refusal_reason": prepared.get("refusal_reason", ""),
                    "safety": prepared.get("safety", {}),
                },
            )
            for citation in prepared.get("citations", []) or []:
                yield encode_sse_event("citation", citation)

            answer_queue: asyncio.Queue[str | None] = asyncio.Queue()

            async def emit_answer(answer_text: str) -> None:
                await answer_queue.put(
                    encode_sse_event(
                        "answer",
                        {
                            "answer": answer_text,
                            "grounding_score": prepared.get("grounding_score", 0),
                            "refusal_reason": prepared.get("refusal_reason", ""),
                        },
                    )
                )

            async def run_answer_stream() -> dict[str, Any]:
                try:
                    return await stream_query_response(prepared=prepared, on_answer=emit_answer)
                finally:
                    await answer_queue.put(None)

            answer_task = asyncio.create_task(run_answer_stream())
            while True:
                chunk = await answer_queue.get()
                if chunk is None:
                    break
                yield chunk
            await answer_task
            yield encode_sse_event("done", {"trace_id": current_trace_id()})
        finally:
            KB_QUERY_INFLIGHT_LIMITER.release(decision.ticket)

    return StreamingResponse(generate(), media_type="text/event-stream")
