from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any

from fastapi import HTTPException, status


def _read_env(*names: str, default: str = "") -> str:
    for name in names:
        raw = os.getenv(name)
        if raw is None:
            continue
        candidate = raw.strip()
        if candidate:
            return candidate
    return default


def _read_bool(*names: str, default: bool) -> bool:
    raw = _read_env(*names, default="")
    if not raw:
        return default
    return raw.lower() in {"1", "true", "yes", "on"}


def _read_float(*names: str, default: float) -> float:
    raw = _read_env(*names, default="")
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _read_int(*names: str, default: int) -> int:
    raw = _read_env(*names, default="")
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _parse_extra_body(raw: str) -> dict[str, Any]:
    if not raw.strip():
        return {}
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="LLM_EXTRA_BODY_JSON is not valid JSON",
        ) from exc
    if not isinstance(payload, dict):
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="LLM_EXTRA_BODY_JSON must be a JSON object",
        )
    return payload


@dataclass(frozen=True)
class LLMSettings:
    enabled: bool
    provider: str
    base_url: str
    api_key: str
    model: str
    common_knowledge_model: str
    timeout_seconds: float
    default_temperature: float
    default_max_tokens: int
    common_knowledge_max_tokens: int
    common_knowledge_history_messages: int
    common_knowledge_history_chars: int
    system_prompt: str
    extra_body: dict[str, Any]

    @property
    def configured(self) -> bool:
        return self.enabled and bool(self.base_url and self.api_key and self.model)

    @property
    def chat_url(self) -> str:
        return f"{self.base_url.rstrip('/')}/chat/completions"


def load_llm_settings() -> LLMSettings:
    api_key = _read_env("LLM_API_KEY", "AI_API_KEY", "DASHSCOPE_API_KEY")
    default_max_tokens = max(_read_int("LLM_MAX_TOKENS", "AI_DEFAULT_MAX_TOKENS", default=2048), 128)
    common_knowledge_max_tokens = max(
        _read_int("LLM_COMMON_KNOWLEDGE_MAX_TOKENS", default=min(default_max_tokens, 512)),
        64,
    )
    return LLMSettings(
        enabled=_read_bool("LLM_ENABLED", "AI_CHAT_ENABLED", default=True),
        provider=_read_env("LLM_PROVIDER", "AI_PROVIDER", default="openai-compatible"),
        base_url=_read_env("LLM_BASE_URL", "AI_BASE_URL").rstrip("/"),
        api_key=api_key,
        model=_read_env("LLM_MODEL", "AI_MODEL"),
        common_knowledge_model=_read_env("LLM_COMMON_KNOWLEDGE_MODEL", default=""),
        timeout_seconds=max(_read_float("LLM_TIMEOUT_SECONDS", "AI_CHAT_TIMEOUT_SECONDS", default=120.0), 10.0),
        default_temperature=min(max(_read_float("LLM_TEMPERATURE", "AI_DEFAULT_TEMPERATURE", default=0.7), 0.0), 2.0),
        default_max_tokens=default_max_tokens,
        common_knowledge_max_tokens=min(common_knowledge_max_tokens, default_max_tokens),
        common_knowledge_history_messages=max(_read_int("LLM_COMMON_KNOWLEDGE_HISTORY_MESSAGES", default=4), 0),
        common_knowledge_history_chars=max(_read_int("LLM_COMMON_KNOWLEDGE_HISTORY_CHARS", default=400), 80),
        system_prompt=_read_env("LLM_SYSTEM_PROMPT", "AI_SYSTEM_PROMPT"),
        extra_body=_parse_extra_body(_read_env("LLM_EXTRA_BODY_JSON", "AI_EXTRA_BODY_JSON", default="{}")),
    )
