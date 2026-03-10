from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass
from typing import Any


LOGGER = logging.getLogger("gateway")


def _read_env(*names: str, default: str = "") -> str:
    for name in names:
        raw = os.getenv(name)
        if raw is None:
            continue
        candidate = raw.strip()
        if candidate:
            return candidate
    return default


def _read_float_env(*names: str, default: float) -> float:
    raw = _read_env(*names, default="")
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _read_int_env(*names: str, default: int) -> int:
    raw = _read_env(*names, default="")
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


KB_SERVICE_URL = os.getenv("KB_SERVICE_URL", "http://kb-service:8200").rstrip("/")
REQUEST_TIMEOUT_SECONDS = float(os.getenv("GATEWAY_TIMEOUT_SECONDS", "180"))
RETRIEVAL_FANOUT_LIMIT = max(_read_int_env("GATEWAY_RETRIEVAL_FANOUT_LIMIT", default=4), 1)
IDEMPOTENCY_TTL_HOURS = max(_read_int_env("GATEWAY_IDEMPOTENCY_TTL_HOURS", default=24), 1)
LLM_PRICE_CURRENCY = (_read_env("LLM_PRICE_CURRENCY", "AI_PRICE_CURRENCY", default="CNY").upper() or "CNY")
LLM_INPUT_PRICE_PER_1K_TOKENS = _read_float_env(
    "LLM_INPUT_PRICE_PER_1K_TOKENS",
    "AI_INPUT_PRICE_PER_1K_TOKENS",
    default=0.0,
)
LLM_OUTPUT_PRICE_PER_1K_TOKENS = _read_float_env(
    "LLM_OUTPUT_PRICE_PER_1K_TOKENS",
    "AI_OUTPUT_PRICE_PER_1K_TOKENS",
    default=0.0,
)

HOP_BY_HOP_HEADERS = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailers",
    "transfer-encoding",
    "upgrade",
    "host",
    "content-length",
}
QUERYABLE_STATUSES = {"fast_index_ready", "hybrid_ready", "enhancing", "ready"}
SHORT_QUESTION_RE = re.compile(r"^(它|他|她|这|那|这里|那里|其|them|it|that|this|they)[\s，,。.!?？]*$", re.IGNORECASE)


@dataclass(frozen=True)
class PriceTier:
    max_input_tokens: int | None
    input_price_per_1k_tokens: float
    output_price_per_1k_tokens: float

    def as_dict(self) -> dict[str, Any]:
        return {
            "max_input_tokens": self.max_input_tokens,
            "input_price_per_1k_tokens": self.input_price_per_1k_tokens,
            "output_price_per_1k_tokens": self.output_price_per_1k_tokens,
        }


@dataclass(frozen=True)
class GatewayRuntimeSettings:
    kb_service_url: str
    request_timeout_seconds: float
    retrieval_fanout_limit: int
    chat_max_in_flight_global: int
    chat_max_in_flight_per_user: int
    idempotency_ttl_hours: int
    llm_price_currency: str
    llm_input_price_per_1k_tokens: float
    llm_output_price_per_1k_tokens: float
    llm_price_tiers: list[PriceTier]


def _load_price_tiers() -> list[PriceTier]:
    raw = _read_env("LLM_PRICE_TIERS_JSON", "AI_PRICE_TIERS_JSON", default="")
    if not raw:
        return []

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        LOGGER.warning("LLM_PRICE_TIERS_JSON is invalid JSON; falling back to flat pricing")
        return []

    if not isinstance(payload, list):
        LOGGER.warning("LLM_PRICE_TIERS_JSON must be a JSON array; falling back to flat pricing")
        return []

    tiers: list[PriceTier] = []
    for item in payload:
        if not isinstance(item, dict):
            LOGGER.warning("LLM_PRICE_TIERS_JSON contains a non-object entry; skipping it")
            continue

        max_input_tokens_raw = item.get("max_input_tokens")
        if max_input_tokens_raw in (None, ""):
            max_input_tokens = None
        else:
            try:
                max_input_tokens = int(max_input_tokens_raw)
            except (TypeError, ValueError):
                LOGGER.warning("LLM_PRICE_TIERS_JSON has an invalid max_input_tokens value; skipping tier")
                continue
            if max_input_tokens <= 0:
                LOGGER.warning("LLM_PRICE_TIERS_JSON max_input_tokens must be positive; skipping tier")
                continue

        try:
            input_price = float(item.get("input_price_per_1k_tokens", 0) or 0)
            output_price = float(item.get("output_price_per_1k_tokens", 0) or 0)
        except (TypeError, ValueError):
            LOGGER.warning("LLM_PRICE_TIERS_JSON has invalid price values; skipping tier")
            continue

        if input_price < 0 or output_price < 0:
            LOGGER.warning("LLM_PRICE_TIERS_JSON price values must be non-negative; skipping tier")
            continue

        tiers.append(
            PriceTier(
                max_input_tokens=max_input_tokens,
                input_price_per_1k_tokens=input_price,
                output_price_per_1k_tokens=output_price,
            )
        )

    finite_tiers = sorted(
        (tier for tier in tiers if tier.max_input_tokens is not None),
        key=lambda tier: tier.max_input_tokens or 0,
    )
    open_ended_tiers = [tier for tier in tiers if tier.max_input_tokens is None]
    return finite_tiers + open_ended_tiers

def load_gateway_runtime_settings() -> GatewayRuntimeSettings:
    return GatewayRuntimeSettings(
        kb_service_url=os.getenv("KB_SERVICE_URL", "http://kb-service:8200").rstrip("/"),
        request_timeout_seconds=float(os.getenv("GATEWAY_TIMEOUT_SECONDS", "180")),
        retrieval_fanout_limit=max(_read_int_env("GATEWAY_RETRIEVAL_FANOUT_LIMIT", default=4), 1),
        chat_max_in_flight_global=max(_read_int_env("GATEWAY_CHAT_MAX_IN_FLIGHT_GLOBAL", default=32), 1),
        chat_max_in_flight_per_user=max(_read_int_env("GATEWAY_CHAT_MAX_IN_FLIGHT_PER_USER", default=4), 1),
        idempotency_ttl_hours=max(_read_int_env("GATEWAY_IDEMPOTENCY_TTL_HOURS", default=24), 1),
        llm_price_currency=(_read_env("LLM_PRICE_CURRENCY", "AI_PRICE_CURRENCY", default="CNY").upper() or "CNY"),
        llm_input_price_per_1k_tokens=_read_float_env(
            "LLM_INPUT_PRICE_PER_1K_TOKENS",
            "AI_INPUT_PRICE_PER_1K_TOKENS",
            default=0.0,
        ),
        llm_output_price_per_1k_tokens=_read_float_env(
            "LLM_OUTPUT_PRICE_PER_1K_TOKENS",
            "AI_OUTPUT_PRICE_PER_1K_TOKENS",
            default=0.0,
        ),
        llm_price_tiers=_load_price_tiers(),
    )
