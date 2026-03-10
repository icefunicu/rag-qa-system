from __future__ import annotations

import time
from typing import Any

from shared.auth import CurrentUser
from shared.prompt_safety import analyze_prompt_safety, apply_safety_response_policy
from shared.tracing import current_trace_id, ensure_trace_id

from .gateway_agent import run_agent_search
from .gateway_answering import classify_evidence, compact_text, generate_grounded_answer
from .gateway_audit_support import write_gateway_audit_event
from .gateway_pricing import estimate_usage_cost, usage_with_meta
from .gateway_runtime import (
    GATEWAY_CHAT_LATENCY_MS,
    GATEWAY_CHAT_REQUESTS_TOTAL,
    GATEWAY_LLM_TOKENS_TOTAL,
    GATEWAY_RETRIEVAL_FANOUT_TOTAL,
    GATEWAY_RETRIEVAL_FANOUT_WALL_MS,
    GATEWAY_SAFETY_EVENTS_TOTAL,
    logger,
    runtime_settings,
)
from .gateway_schemas import ChatScopePayload
from .gateway_scope import normalize_execution_mode


async def prepare_chat_message(
    *,
    session_id: str,
    payload: Any,
    user: CurrentUser,
    load_session_fn: Any,
    default_scope_fn: Any,
    resolve_scope_snapshot_fn: Any,
    recent_history_messages_fn: Any,
    retrieve_scope_evidence_fn: Any,
    fetch_corpus_documents_fn: Any,
) -> dict[str, Any]:
    total_started = time.perf_counter()
    trace_id = ensure_trace_id(current_trace_id(), prefix="gateway-")
    session = load_session_fn(session_id, user)
    scope_payload = payload.scope or ChatScopePayload(**(session.get("scope_json") or default_scope_fn()))
    execution_mode = normalize_execution_mode(
        getattr(payload, "execution_mode", None) or str((session.get("scope_json") or {}).get("execution_mode") or ""),
        default="grounded",
    )
    scope_started = time.perf_counter()
    scope_snapshot = await resolve_scope_snapshot_fn(user, scope_payload)
    scope_snapshot["execution_mode"] = execution_mode
    scope_ms = round((time.perf_counter() - scope_started) * 1000.0, 3)
    history = recent_history_messages_fn(session_id, user, limit=8)
    retrieval_started = time.perf_counter()
    if execution_mode == "agent":
        evidence, contextualized_question, retrieval_meta = await run_agent_search(
            user=user,
            scope_snapshot=scope_snapshot,
            question=payload.question,
            history=history,
            retrieve_scope_evidence_fn=retrieve_scope_evidence_fn,
            fetch_corpus_documents_fn=fetch_corpus_documents_fn,
            kb_service_url=runtime_settings.kb_service_url,
        )
    else:
        evidence, contextualized_question, retrieval_meta = await retrieve_scope_evidence_fn(
            user=user,
            scope_snapshot=scope_snapshot,
            question=payload.question,
            history=history,
        )
    retrieval_ms = round((time.perf_counter() - retrieval_started) * 1000.0, 3)
    answer_mode, evidence_status, grounding_score, refusal_reason = classify_evidence(
        evidence,
        allow_common_knowledge=bool(scope_snapshot.get("allow_common_knowledge")),
    )
    safety = analyze_prompt_safety(
        question=payload.question,
        history=history,
        evidence=evidence,
        prefer_fallback=bool(evidence) and execution_mode in {"grounded", "agent"},
    )
    answer_mode, evidence_status, grounding_score, refusal_reason = apply_safety_response_policy(
        answer_mode=answer_mode,
        evidence_status=evidence_status,
        grounding_score=grounding_score,
        refusal_reason=refusal_reason,
        safety=safety,
        evidence_count=len(evidence),
    )
    if safety.risk_level in {"medium", "high"}:
        GATEWAY_SAFETY_EVENTS_TOTAL.labels(safety.risk_level, safety.action).inc()
    return {
        "session_id": session_id,
        "payload": payload,
        "trace_id": trace_id,
        "scope_snapshot": scope_snapshot,
        "execution_mode": execution_mode,
        "history": history,
        "evidence": evidence,
        "contextualized_question": contextualized_question,
        "retrieval_meta": retrieval_meta,
        "answer_mode": answer_mode,
        "evidence_status": evidence_status,
        "grounding_score": grounding_score,
        "refusal_reason": refusal_reason,
        "safety": safety.as_dict(),
        "timing": {
            "total_started": total_started,
            "scope_ms": scope_ms,
            "retrieval_ms": retrieval_ms,
        },
    }


def build_chat_response_payload(
    *,
    prepared: dict[str, Any],
    answer_payload: dict[str, Any],
    generation_ms: float,
) -> dict[str, Any]:
    total_ms = round((time.perf_counter() - float(prepared["timing"]["total_started"])) * 1000.0, 3)
    strategy_used = (
        "agent_grounded_qa"
        if prepared["execution_mode"] == "agent"
        else "common_knowledge_chat"
        if prepared["answer_mode"] == "common_knowledge"
        else "hybrid_grounded_qa"
    )
    cost_meta = estimate_usage_cost(
        answer_payload["usage"],
        llm_price_tiers=runtime_settings.llm_price_tiers,
        llm_input_price_per_1k_tokens=runtime_settings.llm_input_price_per_1k_tokens,
        llm_output_price_per_1k_tokens=runtime_settings.llm_output_price_per_1k_tokens,
        llm_price_currency=runtime_settings.llm_price_currency,
    )
    return {
        "session_id": prepared["session_id"],
        "execution_mode": prepared["execution_mode"],
        "answer": answer_payload["answer"],
        "answer_mode": prepared["answer_mode"],
        "strategy_used": strategy_used,
        "evidence_status": prepared["evidence_status"],
        "grounding_score": prepared["grounding_score"],
        "refusal_reason": prepared["refusal_reason"],
        "safety": prepared["safety"],
        "citations": prepared["evidence"],
        "evidence_path": [item.get("evidence_path") or {} for item in prepared["evidence"]],
        "provider": answer_payload["provider"],
        "model": answer_payload["model"],
        "usage": answer_payload["usage"],
        "scope_snapshot": prepared["scope_snapshot"],
        "trace_id": prepared["trace_id"],
        "retrieval": prepared["retrieval_meta"],
        "latency": {
            "scope_ms": prepared["timing"]["scope_ms"],
            "retrieval_ms": prepared["timing"]["retrieval_ms"],
            "generation_ms": generation_ms,
            "total_ms": total_ms,
        },
        "cost": cost_meta,
    }


def finalize_chat_message(
    *,
    prepared: dict[str, Any],
    request: Any,
    user: CurrentUser,
    response_payload: dict[str, Any],
    persist_chat_turn_fn: Any,
) -> dict[str, Any]:
    total_ms = float((response_payload.get("latency") or {}).get("total_ms") or 0.0)
    retrieval_ms = float((response_payload.get("latency") or {}).get("retrieval_ms") or 0.0)
    cost_meta = dict(response_payload.get("cost") or {})
    logger.info(
        "chat_turn trace_id=%s mode=%s evidence=%s total_ms=%.3f retrieval_ms=%.3f est_cost=%.6f",
        prepared["trace_id"],
        prepared["answer_mode"],
        len(prepared["evidence"]),
        total_ms,
        retrieval_ms,
        float(cost_meta.get("estimated_cost") or 0.0),
    )
    persisted_message = persist_chat_turn_fn(
        session_id=prepared["session_id"],
        user=user,
        question=prepared["payload"].question,
        session_scope=prepared["scope_snapshot"],
        response_payload=response_payload,
        compact_text_fn=compact_text,
        usage_with_meta_fn=usage_with_meta,
    )
    write_gateway_audit_event(
        action="chat.message.send",
        outcome="blocked" if bool((prepared.get("safety") or {}).get("blocked")) else "success",
        request=request,
        user=user,
        resource_type="chat_session",
        resource_id=prepared["session_id"],
        scope="owner",
        details={
            "answer_mode": prepared["answer_mode"],
            "execution_mode": prepared["execution_mode"],
            "evidence_status": prepared["evidence_status"],
            "safety_risk_level": str((prepared.get("safety") or {}).get("risk_level") or "low"),
            "safety_reason_codes": list((prepared.get("safety") or {}).get("reason_codes") or []),
            "partial_failure": bool((prepared["retrieval_meta"].get("aggregate") or {}).get("partial_failure")),
            "selected_candidates": int((prepared["retrieval_meta"].get("aggregate") or {}).get("selected_candidates", 0) or 0),
        },
    )
    aggregate = dict(prepared["retrieval_meta"].get("aggregate") or {})
    GATEWAY_RETRIEVAL_FANOUT_TOTAL.labels(
        "empty_scope" if aggregate.get("empty_scope") else "partial" if aggregate.get("partial_failure") else "success"
    ).inc()
    GATEWAY_CHAT_REQUESTS_TOTAL.labels("success", prepared["answer_mode"]).inc()
    GATEWAY_CHAT_LATENCY_MS.observe(total_ms)
    if aggregate.get("retrieval_ms") is not None:
        GATEWAY_RETRIEVAL_FANOUT_WALL_MS.observe(float(aggregate.get("retrieval_ms") or 0.0))
    model_name = str(response_payload.get("model") or "fallback")
    usage = dict(response_payload.get("usage") or {})
    GATEWAY_LLM_TOKENS_TOTAL.labels("input", model_name).inc(float(usage.get("prompt_tokens") or 0))
    GATEWAY_LLM_TOKENS_TOTAL.labels("output", model_name).inc(float(usage.get("completion_tokens") or 0))
    response_payload["message"] = persisted_message
    return response_payload


async def handle_chat_message(
    *,
    session_id: str,
    payload: Any,
    request: Any,
    user: CurrentUser,
    load_session_fn: Any,
    default_scope_fn: Any,
    resolve_scope_snapshot_fn: Any,
    recent_history_messages_fn: Any,
    retrieve_scope_evidence_fn: Any,
    fetch_corpus_documents_fn: Any,
    persist_chat_turn_fn: Any,
) -> dict[str, Any]:
    prepared = await prepare_chat_message(
        session_id=session_id,
        payload=payload,
        user=user,
        load_session_fn=load_session_fn,
        default_scope_fn=default_scope_fn,
        resolve_scope_snapshot_fn=resolve_scope_snapshot_fn,
        recent_history_messages_fn=recent_history_messages_fn,
        retrieve_scope_evidence_fn=retrieve_scope_evidence_fn,
        fetch_corpus_documents_fn=fetch_corpus_documents_fn,
    )
    generation_started = time.perf_counter()
    answer_payload = await generate_grounded_answer(
        question=prepared["contextualized_question"],
        history=prepared["history"],
        evidence=prepared["evidence"],
        answer_mode=prepared["answer_mode"],
        safety=prepared["safety"],
    )
    generation_ms = round((time.perf_counter() - generation_started) * 1000.0, 3)
    response_payload = build_chat_response_payload(
        prepared=prepared,
        answer_payload=answer_payload,
        generation_ms=generation_ms,
    )
    return finalize_chat_message(
        prepared=prepared,
        request=request,
        user=user,
        response_payload=response_payload,
        persist_chat_turn_fn=persist_chat_turn_fn,
    )
