from __future__ import annotations

from typing import Any

from fastapi import HTTPException

from shared.grounded_answering import (
    COMMON_KNOWLEDGE_DISCLAIMER,
    build_common_knowledge_prompt,
    build_grounded_prompt,
    classify_evidence,
    compact_history_messages,
    compact_text,
    dicts_to_langchain_messages,
    ensure_citation_markers,
    ensure_common_knowledge_disclaimer,
    evidence_prompt_lines,
    fallback_answer,
    is_low_signal_common_knowledge_question,
    langchain_messages_to_dicts,
    low_signal_common_knowledge_answer,
)
from shared.prompt_safety import augment_settings_prompt, blocked_prompt_answer

from .ai_client import load_llm_settings
from .gateway_config import SHORT_QUESTION_RE
from .gateway_runtime import logger
from .langchain_client import create_llm_completion, create_llm_completion_stream


def contextualize_question(question: str, history: list[dict[str, Any]]) -> str:
    cleaned = question.strip()
    if len(cleaned) >= 20 and not SHORT_QUESTION_RE.search(cleaned):
        return cleaned
    previous_users = [item["content"] for item in history if item["role"] == "user" and item["content"].strip()]
    if not previous_users:
        return cleaned
    previous_question = previous_users[-1]
    if previous_question == cleaned:
        return cleaned
    return previous_question + "\n当前追问：" + cleaned


def common_knowledge_prompt_messages(
    *,
    settings_prompt: str,
    question: str,
    history: list[dict[str, Any]],
    history_limit: int = 4,
    history_chars: int = 400,
) -> list[dict[str, str]]:
    prompt = build_common_knowledge_prompt()
    formatted = prompt.format_messages(
        settings_prompt=augment_settings_prompt(settings_prompt or ""),
        history=dicts_to_langchain_messages(
            compact_history_messages(history, limit=history_limit, content_limit=history_chars)
        ),
        question=question.strip(),
    )
    return langchain_messages_to_dicts(formatted)


def chat_prompt_messages(
    *,
    settings_prompt: str,
    question: str,
    history: list[dict[str, Any]],
    evidence: list[dict[str, Any]],
    answer_mode: str,
) -> list[dict[str, str]]:
    prompt = build_grounded_prompt()
    formatted = prompt.format_messages(
        settings_prompt=augment_settings_prompt(settings_prompt or ""),
        history=dicts_to_langchain_messages(history[-8:]),
        question=question.strip(),
        answer_mode=answer_mode,
        evidence_block=evidence_prompt_lines(evidence),
    )
    return langchain_messages_to_dicts(formatted)


async def generate_grounded_answer(
    *,
    question: str,
    history: list[dict[str, Any]],
    evidence: list[dict[str, Any]],
    answer_mode: str,
    safety: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if bool((safety or {}).get("blocked")):
        return {
            "answer": blocked_prompt_answer(
                question=question,
                evidence=evidence,
                action=str((safety or {}).get("action") or "refuse"),
                fallback_answer_fn=fallback_answer,
            ),
            "provider": "",
            "model": "",
            "usage": {},
        }
    if answer_mode == "refusal":
        return {"answer": fallback_answer(question, evidence, "refusal"), "provider": "", "model": "", "usage": {}}

    settings = load_llm_settings()
    if answer_mode == "common_knowledge":
        if not settings.configured:
            return {"answer": fallback_answer(question, evidence, answer_mode), "provider": "", "model": "", "usage": {}}
        if is_low_signal_common_knowledge_question(question):
            return {"answer": low_signal_common_knowledge_answer(question), "provider": "", "model": "", "usage": {}}
        prompt = build_common_knowledge_prompt()
        inputs = {
            "settings_prompt": augment_settings_prompt(settings.system_prompt or ""),
            "history": dicts_to_langchain_messages(
                compact_history_messages(
                    history,
                    limit=settings.common_knowledge_history_messages,
                    content_limit=settings.common_knowledge_history_chars,
                )
            ),
            "question": question.strip(),
        }
        try:
            completion = await create_llm_completion(
                settings=settings,
                prompt=prompt,
                inputs=inputs,
                model=settings.common_knowledge_model or settings.model,
                temperature=0.4,
                max_tokens=settings.common_knowledge_max_tokens,
            )
            return {
                "answer": ensure_common_knowledge_disclaimer(str(completion["answer"])),
                "provider": completion["provider"],
                "model": completion["model"],
                "usage": completion["usage"],
            }
        except HTTPException:
            logger.warning("llm common knowledge fallback engaged")
            return {"answer": fallback_answer(question, evidence, answer_mode), "provider": "", "model": "", "usage": {}}

    if not settings.configured:
        return {"answer": fallback_answer(question, evidence, answer_mode), "provider": "", "model": "", "usage": {}}

    prompt = build_grounded_prompt()
    inputs = {
        "settings_prompt": augment_settings_prompt(settings.system_prompt or ""),
        "history": dicts_to_langchain_messages(history[-8:]),
        "question": question.strip(),
        "answer_mode": answer_mode,
        "evidence_block": evidence_prompt_lines(evidence),
    }
    try:
        completion = await create_llm_completion(
            settings=settings,
            prompt=prompt,
            inputs=inputs,
            temperature=0.2,
            max_tokens=min(settings.default_max_tokens, 1200),
        )
        return {
            "answer": ensure_citation_markers(str(completion["answer"]), evidence),
            "provider": completion["provider"],
            "model": completion["model"],
            "usage": completion["usage"],
        }
    except HTTPException:
        logger.warning("llm grounded answer fallback engaged")
        return {"answer": fallback_answer(question, evidence, answer_mode), "provider": "", "model": "", "usage": {}}


async def stream_grounded_answer(
    *,
    question: str,
    history: list[dict[str, Any]],
    evidence: list[dict[str, Any]],
    answer_mode: str,
    on_answer: Any,
    safety: dict[str, Any] | None = None,
) -> dict[str, Any]:
    async def emit_answer(answer_text: str) -> None:
        callback_result = on_answer(answer_text)
        if hasattr(callback_result, "__await__"):
            await callback_result

    if bool((safety or {}).get("blocked")):
        answer = blocked_prompt_answer(
            question=question,
            evidence=evidence,
            action=str((safety or {}).get("action") or "refuse"),
            fallback_answer_fn=fallback_answer,
        )
        await emit_answer(answer)
        return {"answer": answer, "provider": "", "model": "", "usage": {}}

    if answer_mode == "refusal":
        answer = fallback_answer(question, evidence, "refusal")
        await emit_answer(answer)
        return {"answer": answer, "provider": "", "model": "", "usage": {}}

    settings = load_llm_settings()
    if answer_mode == "common_knowledge":
        if not settings.configured:
            answer = fallback_answer(question, evidence, answer_mode)
            await emit_answer(answer)
            return {"answer": answer, "provider": "", "model": "", "usage": {}}
        if is_low_signal_common_knowledge_question(question):
            answer = low_signal_common_knowledge_answer(question)
            await emit_answer(answer)
            return {"answer": answer, "provider": "", "model": "", "usage": {}}
        prompt = build_common_knowledge_prompt()
        inputs = {
            "settings_prompt": augment_settings_prompt(settings.system_prompt or ""),
            "history": dicts_to_langchain_messages(
                compact_history_messages(
                    history,
                    limit=settings.common_knowledge_history_messages,
                    content_limit=settings.common_knowledge_history_chars,
                )
            ),
            "question": question.strip(),
        }
        try:
            completion = await create_llm_completion_stream(
                settings=settings,
                prompt=prompt,
                inputs=inputs,
                on_text_delta=lambda _delta, answer_text: emit_answer(answer_text),
                model=settings.common_knowledge_model or settings.model,
                temperature=0.4,
                max_tokens=settings.common_knowledge_max_tokens,
            )
            finalized_answer = ensure_common_knowledge_disclaimer(str(completion["answer"]))
            if finalized_answer != str(completion["answer"]):
                await emit_answer(finalized_answer)
            return {
                "answer": finalized_answer,
                "provider": completion["provider"],
                "model": completion["model"],
                "usage": completion["usage"],
            }
        except HTTPException:
            logger.warning("llm common knowledge fallback engaged")
            answer = fallback_answer(question, evidence, answer_mode)
            await emit_answer(answer)
            return {"answer": answer, "provider": "", "model": "", "usage": {}}

    if not settings.configured:
        answer = fallback_answer(question, evidence, answer_mode)
        await emit_answer(answer)
        return {"answer": answer, "provider": "", "model": "", "usage": {}}

    prompt = build_grounded_prompt()
    inputs = {
        "settings_prompt": augment_settings_prompt(settings.system_prompt or ""),
        "history": dicts_to_langchain_messages(history[-8:]),
        "question": question.strip(),
        "answer_mode": answer_mode,
        "evidence_block": evidence_prompt_lines(evidence),
    }
    try:
        completion = await create_llm_completion_stream(
            settings=settings,
            prompt=prompt,
            inputs=inputs,
            on_text_delta=lambda _delta, answer_text: emit_answer(answer_text),
            temperature=0.2,
            max_tokens=min(settings.default_max_tokens, 1200),
        )
        finalized_answer = ensure_citation_markers(str(completion["answer"]), evidence)
        if finalized_answer != str(completion["answer"]):
            await emit_answer(finalized_answer)
        return {
            "answer": finalized_answer,
            "provider": completion["provider"],
            "model": completion["model"],
            "usage": completion["usage"],
        }
    except HTTPException:
        logger.warning("llm grounded answer fallback engaged")
        answer = fallback_answer(question, evidence, answer_mode)
        await emit_answer(answer)
        return {"answer": answer, "provider": "", "model": "", "usage": {}}


__all__ = [
    "COMMON_KNOWLEDGE_DISCLAIMER",
    "chat_prompt_messages",
    "classify_evidence",
    "common_knowledge_prompt_messages",
    "compact_text",
    "contextualize_question",
    "generate_grounded_answer",
    "stream_grounded_answer",
]
