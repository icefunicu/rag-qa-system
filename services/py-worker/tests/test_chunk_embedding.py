from unittest.mock import MagicMock, patch

from worker.chunking import ParsedSegment, chunk_segments, chunk_segments_by_chars
from worker.config import WorkerConfig
from worker.embedding import EmbeddingClient, hash_embedding, resolve_provider_base_url


def test_chunk_segments_with_overlap() -> None:
    text = " ".join([f"w{i}" for i in range(1, 1001)])
    chunks = chunk_segments([ParsedSegment(text=text, page_or_loc="text:1")], chunk_tokens=200, overlap_tokens=50)
    assert len(chunks) > 1
    assert chunks[0].token_count == 200
    assert chunks[1].token_count == 200
    assert chunks[0].chunk_index == 0
    assert chunks[1].chunk_index == 1


def test_chunk_segments_preserve_original_cjk_text() -> None:
    text = "人工智能正在改变知识处理方式。长文本摄入需要更高吞吐。"
    chunks = chunk_segments([ParsedSegment(text=text, page_or_loc="text:1")], chunk_tokens=6, overlap_tokens=0)

    assert len(chunks) >= 1
    assert " " not in chunks[0].text
    assert chunks[0].text in text


def test_chunk_segments_by_chars_is_fast_path_friendly() -> None:
    text = "abcdefghijklmnopqrstuvwxyz" * 20
    chunks = chunk_segments_by_chars(
        [ParsedSegment(text=text, page_or_loc="text:1")],
        chunk_chars=64,
        overlap_chars=8,
    )

    assert len(chunks) > 1
    assert chunks[0].text == text[:64]
    assert chunks[1].text.startswith(text[56:64])


def test_hash_embedding_dimension_and_norm() -> None:
    vec = hash_embedding("hello world", 64)
    assert len(vec) == 64
    assert abs(sum(v * v for v in vec) - 1.0) < 1e-6


def test_hash_embedding_uses_default_dim_when_auto() -> None:
    vec = hash_embedding("hello world", 0)
    assert len(vec) == 256


def test_resolve_provider_base_url() -> None:
    assert resolve_provider_base_url("deepseek", "") == "https://api.deepseek.com/v1"
    assert resolve_provider_base_url("gemini", "") == "https://generativelanguage.googleapis.com/v1beta"
    assert resolve_provider_base_url("custom", "https://llm.example.com/v1") == "https://llm.example.com/v1"


def test_resolve_provider_base_url_supports_ollama_override(monkeypatch) -> None:
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434")
    assert resolve_provider_base_url("ollama", "") == "http://127.0.0.1:11434/v1"


def _worker_config(**overrides) -> WorkerConfig:
    base = dict(
        postgres_dsn="postgres://rag:rag@localhost:5432/rag?sslmode=disable",
        redis_url="redis://localhost:6379/0",
        ingest_queue_key="ingest_jobs",
        poll_interval_seconds=5,
        worker_max_retries=3,
        s3_endpoint="localhost:9000",
        s3_access_key="minioadmin",
        s3_secret_key="minioadmin",
        s3_bucket="rag-raw",
        s3_use_ssl=False,
        qdrant_url="http://localhost:6333",
        qdrant_collection="rag_chunks",
        embedding_dim=0,
        embedding_batch_size=16,
        embedding_batch_max_chars=24000,
        default_chunk_size=1024,
        default_chunk_overlap=100,
        long_text_mode_enabled=True,
        long_text_threshold_chars=250000,
        long_text_chunk_size=2048,
        long_text_chunk_overlap=32,
        long_text_embedding_batch_size=96,
        long_text_embedding_batch_max_chars=256000,
        long_text_sparse_only_enabled=True,
        long_text_sparse_only_threshold_chars=2000000,
        long_text_sparse_chunk_chars=4096,
        long_text_sparse_chunk_overlap_chars=256,
        embedding_provider="custom",
        embedding_base_url="http://localhost:9999/v1",
        embedding_api_key="",
        embedding_model="local-embedding-model",
        embedding_keep_alive="30m",
        embedding_timeout_seconds=120,
        llm_timeout_seconds=30,
        llm_max_retries=0,
        llm_retry_delay_milliseconds=0,
        metadata_enhancement_enabled=True,
        metadata_max_keywords=5,
    )
    base.update(overrides)
    return WorkerConfig(**base)


def test_embedding_client_custom_provider_omits_auth_header() -> None:
    client = EmbeddingClient(_worker_config())
    mock_response = MagicMock(status_code=200)
    mock_response.json.return_value = {"data": [{"embedding": [0.1, 0.2, 0.3]}]}

    with patch.object(client._client, "post", return_value=mock_response) as mock_post:
        vector = client.embed("hello world")

    assert vector == [0.1, 0.2, 0.3]
    assert "Authorization" not in mock_post.call_args.kwargs["headers"]


def test_embedding_client_openai_compatible_batch_support() -> None:
    client = EmbeddingClient(_worker_config())
    mock_response = MagicMock(status_code=200)
    mock_response.json.return_value = {
        "data": [
            {"index": 0, "embedding": [0.1, 0.2]},
            {"index": 1, "embedding": [0.3, 0.4]},
        ]
    }

    with patch.object(client._client, "post", return_value=mock_response):
        vectors = client.embed_batch(["hello", "world"])

    assert vectors == [[0.1, 0.2], [0.3, 0.4]]


def test_embedding_client_ollama_native_batch_support() -> None:
    client = EmbeddingClient(
        _worker_config(
            embedding_provider="ollama",
            embedding_base_url="http://localhost:11434/v1",
            embedding_model="andersc/qwen3-embedding:0.6b",
        )
    )
    mock_response = MagicMock(status_code=200)
    mock_response.json.return_value = {
        "embeddings": [
            [0.1, 0.2],
            [0.3, 0.4],
        ]
    }

    with patch.object(client._client, "post", return_value=mock_response) as mock_post:
        vectors = client.embed_batch(["hello", "world"])

    assert vectors == [[0.1, 0.2], [0.3, 0.4]]
    assert mock_post.call_args.kwargs["json"]["keep_alive"] == "30m"
    assert mock_post.call_args.kwargs["json"]["input"] == ["hello", "world"]
