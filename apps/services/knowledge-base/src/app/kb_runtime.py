from __future__ import annotations

import os

from shared.logging import setup_logging
from shared.metrics import Counter, Gauge, Histogram

from .runtime import db, prepare_runtime, storage


logger = setup_logging("kb-service")
UPLOAD_PART_EXPIRES_SECONDS = int(os.getenv("UPLOAD_PART_EXPIRES_SECONDS", "3600"))
VISUAL_ASSET_URL_EXPIRES_SECONDS = int(os.getenv("VISUAL_ASSET_URL_EXPIRES_SECONDS", "3600"))
IDEMPOTENCY_TTL_HOURS = max(int(os.getenv("KB_IDEMPOTENCY_TTL_HOURS", "24")), 1)
DEFAULT_INGEST_MAX_ATTEMPTS = max(int(os.getenv("KB_INGEST_MAX_ATTEMPTS", "5")), 1)
KB_QUERY_MAX_IN_FLIGHT_GLOBAL = max(int(os.getenv("KB_QUERY_MAX_IN_FLIGHT_GLOBAL", "64")), 1)
KB_QUERY_MAX_IN_FLIGHT_PER_USER = max(int(os.getenv("KB_QUERY_MAX_IN_FLIGHT_PER_USER", "8")), 1)
KB_READ_PERMISSION = "kb.read"
KB_WRITE_PERMISSION = "kb.write"
KB_MANAGE_PERMISSION = "kb.manage"
CHAT_PERMISSION = "chat.use"
AUDIT_PERMISSION = "audit.read"

KB_UPLOAD_REQUESTS_TOTAL = Counter(
    "rag_kb_upload_requests_total",
    "KB upload requests.",
    labelnames=("result",),
)
KB_RETRIEVE_REQUESTS_TOTAL = Counter(
    "rag_kb_retrieve_requests_total",
    "KB retrieve and query requests.",
    labelnames=("result", "degraded"),
)
KB_RETRIEVE_LATENCY_MS = Histogram(
    "rag_kb_retrieve_latency_ms",
    "KB retrieval latency in milliseconds.",
    buckets=(10, 25, 50, 100, 250, 500, 1000, 2000, 5000),
)
KB_INGEST_JOBS_GAUGE = Gauge(
    "rag_kb_ingest_jobs_total",
    "Current KB ingest jobs by status.",
    labelnames=("status",),
)
KB_DEAD_LETTER_GAUGE = Gauge(
    "rag_kb_dead_letter_total",
    "Current KB dead-letter ingest jobs.",
)
KB_IDEMPOTENCY_TOTAL = Counter(
    "rag_kb_idempotency_total",
    "KB idempotency outcomes.",
    labelnames=("result", "scope"),
)
KB_BACKPRESSURE_TOTAL = Counter(
    "rag_kb_backpressure_total",
    "KB query backpressure rejections.",
    labelnames=("scope", "endpoint"),
)
KB_SAFETY_EVENTS_TOTAL = Counter(
    "rag_kb_safety_events_total",
    "KB prompt safety events.",
    labelnames=("risk_level", "action"),
)


__all__ = [
    "AUDIT_PERMISSION",
    "CHAT_PERMISSION",
    "DEFAULT_INGEST_MAX_ATTEMPTS",
    "IDEMPOTENCY_TTL_HOURS",
    "KB_DEAD_LETTER_GAUGE",
    "KB_IDEMPOTENCY_TOTAL",
    "KB_INGEST_JOBS_GAUGE",
    "KB_MANAGE_PERMISSION",
    "KB_BACKPRESSURE_TOTAL",
    "KB_READ_PERMISSION",
    "KB_RETRIEVE_LATENCY_MS",
    "KB_RETRIEVE_REQUESTS_TOTAL",
    "KB_QUERY_MAX_IN_FLIGHT_GLOBAL",
    "KB_QUERY_MAX_IN_FLIGHT_PER_USER",
    "KB_SAFETY_EVENTS_TOTAL",
    "KB_UPLOAD_REQUESTS_TOTAL",
    "KB_WRITE_PERMISSION",
    "UPLOAD_PART_EXPIRES_SECONDS",
    "VISUAL_ASSET_URL_EXPIRES_SECONDS",
    "db",
    "logger",
    "prepare_runtime",
    "storage",
]
