from worker.config import build_worker_config


def test_build_worker_config_defaults(monkeypatch) -> None:
    monkeypatch.delenv("POSTGRES_DSN", raising=False)
    monkeypatch.delenv("REDIS_URL", raising=False)
    monkeypatch.delenv("INGEST_QUEUE_KEY", raising=False)
    monkeypatch.delenv("WORKER_POLL_INTERVAL_SECONDS", raising=False)
    monkeypatch.delenv("WORKER_MAX_RETRIES", raising=False)
    monkeypatch.delenv("EMBEDDING_DIM", raising=False)
    monkeypatch.delenv("EMBEDDING_BATCH_SIZE", raising=False)
    monkeypatch.delenv("EMBEDDING_BATCH_MAX_CHARS", raising=False)
    monkeypatch.delenv("EMBEDDING_KEEP_ALIVE", raising=False)
    monkeypatch.delenv("EMBEDDING_TIMEOUT_SECONDS", raising=False)
    monkeypatch.delenv("DEFAULT_CHUNK_SIZE", raising=False)
    monkeypatch.delenv("DEFAULT_CHUNK_OVERLAP", raising=False)
    monkeypatch.delenv("LONG_TEXT_MODE_ENABLED", raising=False)
    monkeypatch.delenv("LONG_TEXT_THRESHOLD_CHARS", raising=False)
    monkeypatch.delenv("LONG_TEXT_CHUNK_SIZE", raising=False)
    monkeypatch.delenv("LONG_TEXT_CHUNK_OVERLAP", raising=False)
    monkeypatch.delenv("LONG_TEXT_EMBEDDING_BATCH_SIZE", raising=False)
    monkeypatch.delenv("LONG_TEXT_EMBEDDING_BATCH_MAX_CHARS", raising=False)
    monkeypatch.delenv("LONG_TEXT_SPARSE_ONLY_ENABLED", raising=False)
    monkeypatch.delenv("LONG_TEXT_SPARSE_ONLY_THRESHOLD_CHARS", raising=False)
    monkeypatch.delenv("LONG_TEXT_SPARSE_CHUNK_CHARS", raising=False)
    monkeypatch.delenv("LONG_TEXT_SPARSE_CHUNK_OVERLAP_CHARS", raising=False)
    monkeypatch.delenv("EMBEDDING_PROVIDER", raising=False)
    monkeypatch.delenv("EMBEDDING_BASE_URL", raising=False)
    monkeypatch.delenv("EMBEDDING_API_KEY", raising=False)
    monkeypatch.delenv("EMBEDDING_MODEL", raising=False)
    monkeypatch.delenv("MAX_KEYWORDS", raising=False)
    monkeypatch.delenv("METADATA_MAX_KEYWORDS", raising=False)
    monkeypatch.delenv("LLM_TIMEOUT_SECONDS", raising=False)
    monkeypatch.delenv("LLM_MAX_RETRIES", raising=False)
    monkeypatch.delenv("LLM_RETRY_DELAY_MILLISECONDS", raising=False)

    cfg = build_worker_config()
    assert cfg.redis_url == "redis://redis:6379/0"
    assert cfg.ingest_queue_key == "ingest_jobs"
    assert cfg.poll_interval_seconds == 5
    assert cfg.worker_max_retries == 3
    assert cfg.embedding_dim == 0
    assert cfg.embedding_batch_size == 16
    assert cfg.embedding_batch_max_chars == 24000
    assert cfg.embedding_timeout_seconds == 120
    assert cfg.default_chunk_size == 1024
    assert cfg.default_chunk_overlap == 100
    assert cfg.long_text_mode_enabled is True
    assert cfg.long_text_threshold_chars == 250000
    assert cfg.long_text_chunk_size == 2048
    assert cfg.long_text_chunk_overlap == 32
    assert cfg.long_text_embedding_batch_size == 96
    assert cfg.long_text_embedding_batch_max_chars == 256000
    assert cfg.long_text_sparse_only_enabled is True
    assert cfg.long_text_sparse_only_threshold_chars == 2000000
    assert cfg.long_text_sparse_chunk_chars == 4096
    assert cfg.long_text_sparse_chunk_overlap_chars == 256
    assert cfg.embedding_provider == "openai"
    assert cfg.embedding_base_url == ""
    assert cfg.embedding_api_key == ""
    assert cfg.embedding_model == ""
    assert cfg.embedding_keep_alive == "30m"
    assert cfg.llm_timeout_seconds == 30
    assert cfg.llm_max_retries == 2
    assert cfg.llm_retry_delay_milliseconds == 600


def test_build_worker_config_overrides(monkeypatch) -> None:
    monkeypatch.setenv("REDIS_URL", "redis://custom:6379/1")
    monkeypatch.setenv("INGEST_QUEUE_KEY", "queue-x")
    monkeypatch.setenv("WORKER_POLL_INTERVAL_SECONDS", "9")
    monkeypatch.setenv("WORKER_MAX_RETRIES", "5")
    monkeypatch.setenv("EMBEDDING_DIM", "128")
    monkeypatch.setenv("EMBEDDING_BATCH_SIZE", "24")
    monkeypatch.setenv("EMBEDDING_BATCH_MAX_CHARS", "64000")
    monkeypatch.setenv("EMBEDDING_TIMEOUT_SECONDS", "90")
    monkeypatch.setenv("DEFAULT_CHUNK_SIZE", "640")
    monkeypatch.setenv("DEFAULT_CHUNK_OVERLAP", "64")
    monkeypatch.setenv("LONG_TEXT_MODE_ENABLED", "false")
    monkeypatch.setenv("LONG_TEXT_THRESHOLD_CHARS", "900000")
    monkeypatch.setenv("LONG_TEXT_CHUNK_SIZE", "4096")
    monkeypatch.setenv("LONG_TEXT_CHUNK_OVERLAP", "192")
    monkeypatch.setenv("LONG_TEXT_EMBEDDING_BATCH_SIZE", "96")
    monkeypatch.setenv("LONG_TEXT_EMBEDDING_BATCH_MAX_CHARS", "320000")
    monkeypatch.setenv("LONG_TEXT_SPARSE_ONLY_ENABLED", "false")
    monkeypatch.setenv("LONG_TEXT_SPARSE_ONLY_THRESHOLD_CHARS", "5000000")
    monkeypatch.setenv("LONG_TEXT_SPARSE_CHUNK_CHARS", "8192")
    monkeypatch.setenv("LONG_TEXT_SPARSE_CHUNK_OVERLAP_CHARS", "512")
    monkeypatch.setenv("EMBEDDING_PROVIDER", "gemini")
    monkeypatch.setenv("EMBEDDING_BASE_URL", "")
    monkeypatch.setenv("EMBEDDING_API_KEY", "gemini-test")
    monkeypatch.setenv("EMBEDDING_MODEL", "gemini-embedding-001")
    monkeypatch.setenv("EMBEDDING_KEEP_ALIVE", "10m")
    monkeypatch.setenv("LLM_TIMEOUT_SECONDS", "18")
    monkeypatch.setenv("LLM_MAX_RETRIES", "4")
    monkeypatch.setenv("LLM_RETRY_DELAY_MILLISECONDS", "1200")
    monkeypatch.setenv("MAX_KEYWORDS", "9")

    cfg = build_worker_config()
    assert cfg.redis_url == "redis://custom:6379/1"
    assert cfg.ingest_queue_key == "queue-x"
    assert cfg.poll_interval_seconds == 9
    assert cfg.worker_max_retries == 5
    assert cfg.embedding_dim == 128
    assert cfg.embedding_batch_size == 24
    assert cfg.embedding_batch_max_chars == 64000
    assert cfg.embedding_timeout_seconds == 90
    assert cfg.default_chunk_size == 640
    assert cfg.default_chunk_overlap == 64
    assert cfg.long_text_mode_enabled is False
    assert cfg.long_text_threshold_chars == 900000
    assert cfg.long_text_chunk_size == 4096
    assert cfg.long_text_chunk_overlap == 192
    assert cfg.long_text_embedding_batch_size == 96
    assert cfg.long_text_embedding_batch_max_chars == 320000
    assert cfg.long_text_sparse_only_enabled is False
    assert cfg.long_text_sparse_only_threshold_chars == 5000000
    assert cfg.long_text_sparse_chunk_chars == 8192
    assert cfg.long_text_sparse_chunk_overlap_chars == 512
    assert cfg.embedding_provider == "gemini"
    assert cfg.embedding_base_url == ""
    assert cfg.embedding_api_key == "gemini-test"
    assert cfg.embedding_model == "gemini-embedding-001"
    assert cfg.embedding_keep_alive == "10m"
    assert cfg.llm_timeout_seconds == 18
    assert cfg.llm_max_retries == 4
    assert cfg.llm_retry_delay_milliseconds == 1200
    assert cfg.metadata_max_keywords == 9


def test_build_worker_config_invalid_values_fall_back(monkeypatch) -> None:
    monkeypatch.setenv("WORKER_POLL_INTERVAL_SECONDS", "bad")
    monkeypatch.setenv("EMBEDDING_DIM", "-7")
    monkeypatch.setenv("EMBEDDING_BATCH_SIZE", "0")
    monkeypatch.setenv("EMBEDDING_BATCH_MAX_CHARS", "-9")
    monkeypatch.setenv("EMBEDDING_TIMEOUT_SECONDS", "bad")
    monkeypatch.setenv("LLM_TIMEOUT_SECONDS", "bad")
    monkeypatch.setenv("LONG_TEXT_THRESHOLD_CHARS", "0")
    monkeypatch.setenv("LONG_TEXT_CHUNK_SIZE", "8")
    monkeypatch.setenv("LONG_TEXT_CHUNK_OVERLAP", "2048")
    monkeypatch.setenv("LONG_TEXT_EMBEDDING_BATCH_SIZE", "1")
    monkeypatch.setenv("LONG_TEXT_EMBEDDING_BATCH_MAX_CHARS", "7")
    monkeypatch.setenv("LONG_TEXT_SPARSE_ONLY_THRESHOLD_CHARS", "0")
    monkeypatch.setenv("LONG_TEXT_SPARSE_CHUNK_CHARS", "0")
    monkeypatch.setenv("LONG_TEXT_SPARSE_CHUNK_OVERLAP_CHARS", "999999")
    monkeypatch.setenv("METADATA_ENHANCEMENT_ENABLED", "yes")

    cfg = build_worker_config()

    assert cfg.poll_interval_seconds == 5
    assert cfg.embedding_dim == 0
    assert cfg.embedding_batch_size == 16
    assert cfg.embedding_batch_max_chars == 24000
    assert cfg.embedding_timeout_seconds == 120
    assert cfg.llm_timeout_seconds == 30
    assert cfg.long_text_threshold_chars == 250000
    assert cfg.long_text_chunk_size == 1024
    assert cfg.long_text_chunk_overlap == 64
    assert cfg.long_text_embedding_batch_size == 16
    assert cfg.long_text_embedding_batch_max_chars == 24000
    assert cfg.long_text_sparse_only_threshold_chars == 2000000
    assert cfg.long_text_sparse_chunk_chars == 4096
    assert cfg.long_text_sparse_chunk_overlap_chars == 256
    assert cfg.metadata_enhancement_enabled is True
