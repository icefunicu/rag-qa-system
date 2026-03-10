from __future__ import annotations

from shared.logging import setup_logging
from shared.metrics import Counter, Histogram

from .db import GatewayDatabase, MIGRATIONS_DIR, POSTGRES_DSN
from .gateway_config import load_gateway_runtime_settings


logger = setup_logging("gateway")
runtime_settings = load_gateway_runtime_settings()
CHAT_PERMISSION = "chat.use"
AUDIT_PERMISSION = "audit.read"
gateway_db = GatewayDatabase(POSTGRES_DSN, MIGRATIONS_DIR)

GATEWAY_CHAT_REQUESTS_TOTAL = Counter(
    "rag_gateway_chat_requests_total",
    "Total gateway chat requests.",
    labelnames=("result", "mode"),
)
GATEWAY_CHAT_LATENCY_MS = Histogram(
    "rag_gateway_chat_latency_ms",
    "Gateway chat request latency in milliseconds.",
    buckets=(50, 100, 250, 500, 1000, 2000, 5000, 15000),
)
GATEWAY_RETRIEVAL_FANOUT_TOTAL = Counter(
    "rag_gateway_retrieval_fanout_total",
    "Gateway retrieval fanout outcomes.",
    labelnames=("result",),
)
GATEWAY_RETRIEVAL_FANOUT_WALL_MS = Histogram(
    "rag_gateway_retrieval_fanout_wall_ms",
    "Gateway retrieval fanout wall time in milliseconds.",
    buckets=(10, 25, 50, 100, 250, 500, 1000, 2000, 5000),
)
GATEWAY_BACKPRESSURE_TOTAL = Counter(
    "rag_gateway_backpressure_total",
    "Gateway backpressure rejections.",
    labelnames=("scope", "endpoint"),
)
GATEWAY_SAFETY_EVENTS_TOTAL = Counter(
    "rag_gateway_safety_events_total",
    "Gateway prompt safety events.",
    labelnames=("risk_level", "action"),
)
GATEWAY_LLM_TOKENS_TOTAL = Counter(
    "rag_gateway_llm_tokens_total",
    "Gateway LLM token usage.",
    labelnames=("direction", "model"),
)
GATEWAY_IDEMPOTENCY_TOTAL = Counter(
    "rag_gateway_idempotency_total",
    "Gateway idempotency outcomes.",
    labelnames=("result", "scope"),
)
GATEWAY_AUDIT_WRITE_FAILURES_TOTAL = Counter(
    "rag_gateway_audit_write_failures_total",
    "Gateway audit write failures.",
)
