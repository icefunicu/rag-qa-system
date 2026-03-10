from __future__ import annotations

from typing import Any

from fastapi import HTTPException
from shared.grounded_answering import (
    build_grounded_prompt,
    classify_evidence,
    dicts_to_langchain_messages,
    ensure_citation_markers,
    evidence_prompt_lines,
    fallback_answer,
)
from shared.langchain_chat import invoke_prompt_chain, stream_prompt_chain
from shared.llm_settings import load_llm_settings
from shared.prompt_safety import (
    analyze_prompt_safety,
    apply_safety_response_policy,
    augment_settings_prompt,
    blocked_prompt_answer,
)
from shared.tracing import current_trace_id

from .query import build_refusal_response, detect_strategy
from .retrieve import retrieve_kb_result


def serialize_evidence(item: Any, *, corpus_id: str) -> dict[str, Any]:
    payload = item.as_dict()
    payload["corpus_id"] = corpus_id
    payload["service_type"] = "kb"
    return payload


def prepare_query_response(*, base_id: str, question: str, document_ids: list[str]) -> dict[str, Any]:
    strategy = detect_strategy(question)
    retrieval = retrieve_kb_result(
        base_id=base_id,
        question=question,
        document_ids=document_ids,
        limit=8,
    )
    citations = [serialize_evidence(item, corpus_id=f"kb:{base_id}") for item in retrieval.items]
    answer_mode, evidence_status, grounding_score, refusal_reason = classify_evidence(
        citations,
        allow_common_knowledge=False,
    )
    safety = analyze_prompt_safety(
        question=question,
        history=[],
        evidence=citations,
        prefer_fallback=bool(citations),
    )
    answer_mode, evidence_status, grounding_score, refusal_reason = apply_safety_response_policy(
        answer_mode=answer_mode,
        evidence_status=evidence_status,
        grounding_score=grounding_score,
        refusal_reason=refusal_reason,
        safety=safety,
        evidence_count=len(citations),
    )
    return {
        "base_id": base_id,
        "question": question,
        "strategy_used": strategy,
        "retrieval": retrieval.stats.as_dict(),
        "citations": citations,
        "answer_mode": answer_mode,
        "evidence_status": evidence_status,
        "grounding_score": grounding_score,
        "refusal_reason": refusal_reason,
        "safety": safety.as_dict(),
        "trace_id": current_trace_id(),
    }


async def build_query_response(*, base_id: str, question: str, document_ids: list[str]) -> dict[str, Any]:
    prepared = prepare_query_response(base_id=base_id, question=question, document_ids=document_ids)
    answer = await _generate_query_answer(prepared=prepared)
    return _finalize_query_response(prepared=prepared, answer=answer)


async def stream_query_response(*, prepared: dict[str, Any], on_answer: Any) -> dict[str, Any]:
    answer = await _stream_query_answer(prepared=prepared, on_answer=on_answer)
    return _finalize_query_response(prepared=prepared, answer=answer)


async def _generate_query_answer(*, prepared: dict[str, Any]) -> str:
    if bool((prepared.get("safety") or {}).get("blocked")):
        return blocked_prompt_answer(
            question=prepared["question"],
            evidence=prepared["citations"],
            action=str((prepared.get("safety") or {}).get("action") or "refuse"),
            fallback_answer_fn=fallback_answer,
        )
    if prepared["answer_mode"] == "refusal":
        return fallback_answer(prepared["question"], prepared["citations"], "refusal")
    settings = load_llm_settings()
    if not settings.configured:
        return fallback_answer(prepared["question"], prepared["citations"], prepared["answer_mode"])
    prompt = build_grounded_prompt()
    inputs = {
        "settings_prompt": augment_settings_prompt(settings.system_prompt or ""),
        "history": dicts_to_langchain_messages([]),
        "question": prepared["question"].strip(),
        "answer_mode": prepared["answer_mode"],
        "evidence_block": evidence_prompt_lines(prepared["citations"]),
    }
    try:
        completion = await invoke_prompt_chain(
            settings=settings,
            prompt=prompt,
            inputs=inputs,
            temperature=0.2,
            max_tokens=min(settings.default_max_tokens, 1200),
        )
        return ensure_citation_markers(str(completion["answer"]), prepared["citations"])
    except HTTPException:
        return fallback_answer(prepared["question"], prepared["citations"], prepared["answer_mode"])


async def _stream_query_answer(*, prepared: dict[str, Any], on_answer: Any) -> str:
    async def emit_answer(answer_text: str) -> None:
        callback_result = on_answer(answer_text)
        if hasattr(callback_result, "__await__"):
            await callback_result

    if bool((prepared.get("safety") or {}).get("blocked")):
        answer = blocked_prompt_answer(
            question=prepared["question"],
            evidence=prepared["citations"],
            action=str((prepared.get("safety") or {}).get("action") or "refuse"),
            fallback_answer_fn=fallback_answer,
        )
        await emit_answer(answer)
        return answer
    if prepared["answer_mode"] == "refusal":
        answer = fallback_answer(prepared["question"], prepared["citations"], "refusal")
        await emit_answer(answer)
        return answer
    settings = load_llm_settings()
    if not settings.configured:
        answer = fallback_answer(prepared["question"], prepared["citations"], prepared["answer_mode"])
        await emit_answer(answer)
        return answer
    prompt = build_grounded_prompt()
    inputs = {
        "settings_prompt": augment_settings_prompt(settings.system_prompt or ""),
        "history": dicts_to_langchain_messages([]),
        "question": prepared["question"].strip(),
        "answer_mode": prepared["answer_mode"],
        "evidence_block": evidence_prompt_lines(prepared["citations"]),
    }
    try:
        completion = await stream_prompt_chain(
            settings=settings,
            prompt=prompt,
            inputs=inputs,
            on_text_delta=lambda _delta, answer_text: emit_answer(answer_text),
            temperature=0.2,
            max_tokens=min(settings.default_max_tokens, 1200),
        )
        finalized_answer = ensure_citation_markers(str(completion["answer"]), prepared["citations"])
        if finalized_answer != str(completion["answer"]):
            await emit_answer(finalized_answer)
        return finalized_answer
    except HTTPException:
        answer = fallback_answer(prepared["question"], prepared["citations"], prepared["answer_mode"])
        await emit_answer(answer)
        return answer


def _finalize_query_response(*, prepared: dict[str, Any], answer: str) -> dict[str, Any]:
    if not prepared["citations"]:
        result = build_refusal_response(strategy=prepared["strategy_used"], reason="no_relevant_evidence")
        result["answer"] = answer
        result["answer_mode"] = "refusal"
        result["refusal_reason"] = prepared["refusal_reason"]
        result["evidence_path"] = []
        result["retrieval"] = prepared["retrieval"]
        result["safety"] = prepared["safety"]
        result["trace_id"] = prepared["trace_id"]
        return result
    return {
        "answer": answer,
        "answer_mode": prepared["answer_mode"],
        "strategy_used": prepared["strategy_used"],
        "evidence_status": prepared["evidence_status"],
        "grounding_score": prepared["grounding_score"],
        "refusal_reason": prepared["refusal_reason"],
        "safety": prepared["safety"],
        "citations": prepared["citations"],
        "evidence_path": [item["evidence_path"] for item in prepared["citations"]],
        "retrieval": prepared["retrieval"],
        "trace_id": prepared["trace_id"],
    }
