from __future__ import annotations

from typing import Any

from fastapi import HTTPException, status
from langchain_core.messages import AIMessage, AIMessageChunk, BaseMessage
from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI

from .llm_settings import LLMSettings


def build_chat_model(
    *,
    settings: LLMSettings,
    model: str | None,
    temperature: float | None,
    max_tokens: int | None,
    streaming: bool,
) -> ChatOpenAI:
    return ChatOpenAI(
        model_name=(model or settings.model).strip(),
        openai_api_key=settings.api_key,
        openai_api_base=settings.base_url,
        request_timeout=settings.timeout_seconds,
        temperature=settings.default_temperature if temperature is None else temperature,
        max_tokens=settings.default_max_tokens if max_tokens is None else max_tokens,
        extra_body=settings.extra_body or None,
        streaming=streaming,
        stream_usage=True,
        max_retries=0,
    )


def _usage_payload(message: AIMessage | AIMessageChunk) -> dict[str, Any]:
    usage = dict(getattr(message, "usage_metadata", {}) or {})
    if usage:
        return {
            "prompt_tokens": int(usage.get("input_tokens") or 0),
            "completion_tokens": int(usage.get("output_tokens") or 0),
            "total_tokens": int(usage.get("total_tokens") or 0),
        }
    response_metadata = dict(getattr(message, "response_metadata", {}) or {})
    token_usage = dict(response_metadata.get("token_usage") or {})
    return {
        "prompt_tokens": int(token_usage.get("prompt_tokens") or 0),
        "completion_tokens": int(token_usage.get("completion_tokens") or 0),
        "total_tokens": int(token_usage.get("total_tokens") or 0),
    }


def extract_message_text(message: AIMessage | AIMessageChunk) -> str:
    content = getattr(message, "content", "")
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str) and item.strip():
                parts.append(item.strip())
                continue
            if not isinstance(item, dict):
                continue
            text_value = item.get("text")
            if isinstance(text_value, str) and text_value.strip():
                parts.append(text_value.strip())
        return "\n".join(parts).strip()
    return ""


def _ensure_llm_enabled(settings: LLMSettings) -> None:
    if not settings.enabled:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="LLM answer generation is disabled",
        )
    if not settings.configured:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="LLM answer generation is not configured",
        )


async def invoke_prompt_chain(
    *,
    settings: LLMSettings,
    prompt: ChatPromptTemplate,
    inputs: dict[str, Any],
    model: str | None = None,
    temperature: float | None = None,
    max_tokens: int | None = None,
) -> dict[str, Any]:
    _ensure_llm_enabled(settings)
    try:
        chat_model = build_chat_model(
            settings=settings,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            streaming=False,
        )
        chain = prompt | chat_model
        result = await chain.ainvoke(inputs)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Upstream LLM service is unavailable",
        ) from exc

    answer = extract_message_text(result)
    if not answer:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Upstream LLM service returned an empty answer",
        )
    response_metadata = dict(getattr(result, "response_metadata", {}) or {})
    return {
        "answer": answer,
        "reasoning": "",
        "model": str(response_metadata.get("model_name") or model or settings.model),
        "provider": settings.provider,
        "finish_reason": str(response_metadata.get("finish_reason") or ""),
        "usage": _usage_payload(result),
    }


async def stream_prompt_chain(
    *,
    settings: LLMSettings,
    prompt: ChatPromptTemplate,
    inputs: dict[str, Any],
    on_text_delta: Any,
    model: str | None = None,
    temperature: float | None = None,
    max_tokens: int | None = None,
) -> dict[str, Any]:
    _ensure_llm_enabled(settings)
    answer_parts: list[str] = []
    usage: dict[str, Any] = {}
    finish_reason = ""
    resolved_model = model or settings.model
    try:
        chat_model = build_chat_model(
            settings=settings,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            streaming=True,
        )
        chain = prompt | chat_model
        async for chunk in chain.astream(inputs):
            delta = extract_message_text(chunk)
            if delta:
                answer_parts.append(delta)
                callback_result = on_text_delta(delta, "".join(answer_parts))
                if hasattr(callback_result, "__await__"):
                    await callback_result
            usage = _usage_payload(chunk) or usage
            response_metadata = dict(getattr(chunk, "response_metadata", {}) or {})
            finish_reason = str(response_metadata.get("finish_reason") or finish_reason)
            resolved_model = str(response_metadata.get("model_name") or resolved_model)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Upstream LLM service is unavailable",
        ) from exc

    answer = "".join(answer_parts).strip()
    if not answer:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Upstream LLM service returned an empty answer",
        )
    return {
        "answer": answer,
        "reasoning": "",
        "model": resolved_model,
        "provider": settings.provider,
        "finish_reason": finish_reason,
        "usage": usage,
    }
