from __future__ import annotations

import os
from dataclasses import dataclass


def _getenv_int(name: str, fallback: int) -> int:
    raw = os.getenv(name, "").strip()
    if not raw:
        return fallback
    try:
        return int(raw)
    except ValueError:
        return fallback


def _getenv_float(name: str, fallback: float) -> float:
    raw = os.getenv(name, "").strip()
    if not raw:
        return fallback
    try:
        return float(raw)
    except ValueError:
        return fallback


def _getenv_bool(name: str, fallback: bool) -> bool:
    raw = os.getenv(name, "").strip().lower()
    if not raw:
        return fallback
    return raw in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class WorkerConfig:
    postgres_dsn: str
    redis_url: str
    ingest_queue_key: str
    poll_interval_seconds: int
    worker_max_retries: int

    s3_endpoint: str
    s3_access_key: str
    s3_secret_key: str
    s3_bucket: str
    s3_use_ssl: bool

    qdrant_url: str
    qdrant_collection: str
    embedding_dim: int
    embedding_batch_size: int
    embedding_batch_max_chars: int
    default_chunk_size: int
    default_chunk_overlap: int
    long_text_mode_enabled: bool
    long_text_threshold_chars: int
    long_text_chunk_size: int
    long_text_chunk_overlap: int
    long_text_embedding_batch_size: int
    long_text_embedding_batch_max_chars: int
    long_text_sparse_only_enabled: bool
    long_text_sparse_only_threshold_chars: int
    long_text_sparse_chunk_chars: int
    long_text_sparse_chunk_overlap_chars: int
    section_summary_threshold_chars: int = 250000
    section_summary_chars: int = 2000
    metadata_sampling_max_chars: int = 120000
    search_terms_max_per_chunk: int = 64

    embedding_provider: str = "openai"
    embedding_base_url: str = ""
    embedding_api_key: str = ""
    embedding_model: str = ""
    embedding_keep_alive: str = "30m"
    embedding_timeout_seconds: float = 120.0
    llm_timeout_seconds: float = 30.0
    llm_max_retries: int = 2
    llm_retry_delay_milliseconds: int = 600

    metadata_enhancement_enabled: bool = True
    metadata_max_keywords: int = 5


def build_worker_config() -> WorkerConfig:
    poll_interval = _getenv_int("WORKER_POLL_INTERVAL_SECONDS", 5)
    max_retries = _getenv_int("WORKER_MAX_RETRIES", 3)
    embedding_dim = _getenv_int("EMBEDDING_DIM", 0)
    embedding_batch_size = _getenv_int("EMBEDDING_BATCH_SIZE", 16)
    embedding_batch_max_chars = _getenv_int("EMBEDDING_BATCH_MAX_CHARS", 24000)
    default_chunk_size = _getenv_int("DEFAULT_CHUNK_SIZE", 1024)
    default_chunk_overlap = _getenv_int("DEFAULT_CHUNK_OVERLAP", 100)
    long_text_mode_enabled = _getenv_bool("LONG_TEXT_MODE_ENABLED", True)
    long_text_threshold_chars = _getenv_int("LONG_TEXT_THRESHOLD_CHARS", 250000)
    long_text_chunk_size = _getenv_int("LONG_TEXT_CHUNK_SIZE", 2048)
    long_text_chunk_overlap = _getenv_int("LONG_TEXT_CHUNK_OVERLAP", 32)
    long_text_embedding_batch_size = _getenv_int("LONG_TEXT_EMBEDDING_BATCH_SIZE", 96)
    long_text_embedding_batch_max_chars = _getenv_int("LONG_TEXT_EMBEDDING_BATCH_MAX_CHARS", 256000)
    long_text_sparse_only_enabled = _getenv_bool("LONG_TEXT_SPARSE_ONLY_ENABLED", True)
    long_text_sparse_only_threshold_chars = _getenv_int("LONG_TEXT_SPARSE_ONLY_THRESHOLD_CHARS", 2000000)
    long_text_sparse_chunk_chars = _getenv_int("LONG_TEXT_SPARSE_CHUNK_CHARS", 4096)
    long_text_sparse_chunk_overlap_chars = _getenv_int("LONG_TEXT_SPARSE_CHUNK_OVERLAP_CHARS", 256)
    section_summary_threshold_chars = _getenv_int("SECTION_SUMMARY_THRESHOLD_CHARS", 250000)
    section_summary_chars = _getenv_int("SECTION_SUMMARY_CHARS", 2000)
    metadata_sampling_max_chars = _getenv_int("METADATA_SAMPLING_MAX_CHARS", 120000)
    search_terms_max_per_chunk = _getenv_int("SEARCH_TERMS_MAX_PER_CHUNK", 64)
    llm_timeout_seconds = _getenv_float("LLM_TIMEOUT_SECONDS", 30)
    embedding_timeout_seconds = _getenv_float("EMBEDDING_TIMEOUT_SECONDS", max(llm_timeout_seconds, 120))
    llm_max_retries = _getenv_int("LLM_MAX_RETRIES", 2)
    llm_retry_delay_milliseconds = _getenv_int("LLM_RETRY_DELAY_MILLISECONDS", 600)
    metadata_enhancement_enabled = _getenv_bool("METADATA_ENHANCEMENT_ENABLED", True)
    metadata_max_keywords = _getenv_int("METADATA_MAX_KEYWORDS", _getenv_int("MAX_KEYWORDS", 5))

    if poll_interval <= 0:
        poll_interval = 5
    if max_retries < 0:
        max_retries = 0
    if embedding_dim < 0:
        embedding_dim = 0
    if embedding_batch_size <= 0:
        embedding_batch_size = 16
    if embedding_batch_max_chars <= 0:
        embedding_batch_max_chars = 24000
    if default_chunk_size <= 0:
        default_chunk_size = 1024
    if default_chunk_overlap < 0:
        default_chunk_overlap = 0
    if default_chunk_overlap >= default_chunk_size:
        default_chunk_overlap = max(default_chunk_size // 8, 0)
    if long_text_threshold_chars <= 0:
        long_text_threshold_chars = 250000
    if long_text_sparse_only_threshold_chars <= 0:
        long_text_sparse_only_threshold_chars = 2000000
    if long_text_sparse_chunk_chars <= 0:
        long_text_sparse_chunk_chars = 4096
    if long_text_sparse_chunk_overlap_chars < 0:
        long_text_sparse_chunk_overlap_chars = 0
    if long_text_sparse_chunk_overlap_chars >= long_text_sparse_chunk_chars:
        long_text_sparse_chunk_overlap_chars = max(long_text_sparse_chunk_chars // 16, 0)
    if section_summary_threshold_chars <= 0:
        section_summary_threshold_chars = 250000
    if section_summary_chars <= 0:
        section_summary_chars = 2000
    if metadata_sampling_max_chars <= 0:
        metadata_sampling_max_chars = 120000
    if search_terms_max_per_chunk <= 0:
        search_terms_max_per_chunk = 64
    if long_text_chunk_size < default_chunk_size:
        long_text_chunk_size = default_chunk_size
    if long_text_chunk_overlap < 0:
        long_text_chunk_overlap = max(long_text_chunk_size // 16, 0)
    if long_text_chunk_overlap >= long_text_chunk_size:
        long_text_chunk_overlap = max(long_text_chunk_size // 16, 0)
    if long_text_embedding_batch_size < embedding_batch_size:
        long_text_embedding_batch_size = embedding_batch_size
    if long_text_embedding_batch_max_chars < embedding_batch_max_chars:
        long_text_embedding_batch_max_chars = embedding_batch_max_chars
    if llm_timeout_seconds <= 0:
        llm_timeout_seconds = 30
    if embedding_timeout_seconds <= 0:
        embedding_timeout_seconds = max(llm_timeout_seconds, 120)
    if llm_max_retries < 0:
        llm_max_retries = 0
    if llm_retry_delay_milliseconds < 0:
        llm_retry_delay_milliseconds = 0
    if metadata_max_keywords <= 0:
        metadata_max_keywords = 5

    return WorkerConfig(
        postgres_dsn=os.getenv("POSTGRES_DSN", "postgres://rag:rag@postgres:5432/rag?sslmode=disable"),
        redis_url=os.getenv("REDIS_URL", "redis://redis:6379/0"),
        ingest_queue_key=os.getenv("INGEST_QUEUE_KEY", "ingest_jobs"),
        poll_interval_seconds=poll_interval,
        worker_max_retries=max_retries,
        s3_endpoint=os.getenv("S3_ENDPOINT", "minio:9000"),
        s3_access_key=os.getenv("S3_ACCESS_KEY", "minioadmin"),
        s3_secret_key=os.getenv("S3_SECRET_KEY", "minioadmin"),
        s3_bucket=os.getenv("S3_BUCKET", "rag-raw"),
        s3_use_ssl=os.getenv("S3_USE_SSL", "false").lower() == "true",
        qdrant_url=os.getenv("QDRANT_URL", "http://qdrant:6333"),
        qdrant_collection=os.getenv("QDRANT_COLLECTION", "rag_chunks"),
        embedding_dim=embedding_dim,
        embedding_batch_size=embedding_batch_size,
        embedding_batch_max_chars=embedding_batch_max_chars,
        default_chunk_size=default_chunk_size,
        default_chunk_overlap=default_chunk_overlap,
        long_text_mode_enabled=long_text_mode_enabled,
        long_text_threshold_chars=long_text_threshold_chars,
        long_text_chunk_size=long_text_chunk_size,
        long_text_chunk_overlap=long_text_chunk_overlap,
        long_text_embedding_batch_size=long_text_embedding_batch_size,
        long_text_embedding_batch_max_chars=long_text_embedding_batch_max_chars,
        long_text_sparse_only_enabled=long_text_sparse_only_enabled,
        long_text_sparse_only_threshold_chars=long_text_sparse_only_threshold_chars,
        long_text_sparse_chunk_chars=long_text_sparse_chunk_chars,
        long_text_sparse_chunk_overlap_chars=long_text_sparse_chunk_overlap_chars,
        section_summary_threshold_chars=section_summary_threshold_chars,
        section_summary_chars=section_summary_chars,
        metadata_sampling_max_chars=metadata_sampling_max_chars,
        search_terms_max_per_chunk=search_terms_max_per_chunk,
        embedding_provider=os.getenv("EMBEDDING_PROVIDER", "openai").strip().lower() or "openai",
        embedding_base_url=os.getenv("EMBEDDING_BASE_URL", "").strip(),
        embedding_api_key=os.getenv("EMBEDDING_API_KEY", "").strip(),
        embedding_model=os.getenv("EMBEDDING_MODEL", "").strip(),
        embedding_keep_alive=os.getenv("EMBEDDING_KEEP_ALIVE", "30m").strip(),
        embedding_timeout_seconds=embedding_timeout_seconds,
        llm_timeout_seconds=llm_timeout_seconds,
        llm_max_retries=llm_max_retries,
        llm_retry_delay_milliseconds=llm_retry_delay_milliseconds,
        metadata_enhancement_enabled=metadata_enhancement_enabled,
        metadata_max_keywords=metadata_max_keywords,
    )
