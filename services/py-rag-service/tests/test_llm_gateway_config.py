from unittest.mock import MagicMock, patch

from app.main import LLMGateway, ServiceConfig, _resolve_provider_base_url, build_service_config


def _service_config(**overrides):
    base = dict(
        postgres_dsn="postgres://rag:rag@localhost:5432/rag?sslmode=disable",
        qdrant_url="http://localhost:6333",
        qdrant_collection="rag_chunks",
        embedding_dim=256,
        retrieval_top_n=24,
        rerank_top_k=8,
        source_sentence_limit=6,
        evidence_min_score=0.05,
        common_knowledge_max_ratio=0.15,
        embedding_provider="gemini",
        embedding_base_url="",
        embedding_api_key="gemini-test-key",
        embedding_model="gemini-embedding-001",
        chat_provider="qwen",
        chat_base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        chat_api_key="qwen-test-key",
        chat_model="qwen-plus",
        llm_timeout_seconds=30,
        llm_max_retries=2,
        llm_retry_delay_milliseconds=100,
        hybrid_dense_weight=0.7,
        hybrid_sparse_weight=0.3,
        reranker_model="cross-encoder/ms-marco-MiniLM-L-6-v2",
        query_cache_enabled=True,
        query_cache_ttl_hours=24,
        query_cache_max_size=10000,
        sparse_retrieval_enabled=False,
        sparse_cache_ttl_seconds=600,
        sparse_cache_max_scopes=16,
        multi_query_enabled=False,
        multi_query_max_variants=3,
        multi_query_timeout_ms=500,
    )
    base.update(overrides)
    return ServiceConfig(**base)


def test_build_service_config_uses_explicit_chat_and_embedding_env(monkeypatch) -> None:
    monkeypatch.setenv("EMBEDDING_PROVIDER", "gemini")
    monkeypatch.setenv("EMBEDDING_BASE_URL", "")
    monkeypatch.setenv("EMBEDDING_API_KEY", "gemini-key")
    monkeypatch.setenv("EMBEDDING_MODEL", "gemini-embedding-001")
    monkeypatch.setenv("CHAT_PROVIDER", "qwen")
    monkeypatch.setenv("CHAT_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1")
    monkeypatch.setenv("CHAT_API_KEY", "qwen-key")
    monkeypatch.setenv("CHAT_MODEL", "qwen-plus")

    cfg = build_service_config()

    assert cfg.embedding_provider == "gemini"
    assert cfg.embedding_base_url == ""
    assert cfg.embedding_api_key == "gemini-key"
    assert cfg.embedding_model == "gemini-embedding-001"
    assert cfg.chat_provider == "qwen"
    assert cfg.chat_base_url == "https://dashscope.aliyuncs.com/compatible-mode/v1"
    assert cfg.chat_api_key == "qwen-key"
    assert cfg.chat_model == "qwen-plus"


def test_gemini_embedding_uses_direct_endpoint_and_dimension() -> None:
    gateway = LLMGateway(_service_config())
    mock_response = MagicMock(status_code=200)
    mock_response.json.return_value = {
        "embedding": {
            "values": [3.0, 4.0],
        }
    }

    with patch.object(gateway._client, "post", return_value=mock_response) as mock_post:
        vector = gateway.embed("测试问题")

    assert len(vector) == 2
    assert abs(sum(v * v for v in vector) - 1.0) < 1e-6

    args, kwargs = mock_post.call_args
    assert args[0].endswith("/models/gemini-embedding-001:embedContent")
    assert kwargs["headers"]["x-goog-api-key"] == "gemini-test-key"
    assert kwargs["json"]["task_type"] == "RETRIEVAL_QUERY"
    assert kwargs["json"]["output_dimensionality"] == 256


def test_build_service_config_allows_auto_embedding_dim(monkeypatch) -> None:
    monkeypatch.setenv("EMBEDDING_DIM", "0")

    cfg = build_service_config()

    assert cfg.embedding_dim == 0


def test_build_service_config_normalizes_hybrid_weights(monkeypatch) -> None:
    monkeypatch.setenv("HYBRID_SEARCH_DENSE_WEIGHT", "1")
    monkeypatch.setenv("HYBRID_SEARCH_SPARSE_WEIGHT", "1")

    cfg = build_service_config()

    assert round(cfg.hybrid_dense_weight + cfg.hybrid_sparse_weight, 6) == 1.0
    assert cfg.hybrid_dense_weight == 0.5
    assert cfg.hybrid_sparse_weight == 0.5


def test_custom_provider_without_api_key_can_request_openai_compatible_endpoint() -> None:
    gateway = LLMGateway(
        _service_config(
            embedding_provider="custom",
            embedding_base_url="http://localhost:8001/v1",
            embedding_api_key="",
            embedding_model="local-embedding",
        )
    )
    mock_response = MagicMock(status_code=200)
    mock_response.json.return_value = {"data": [{"embedding": [0.1, 0.2]}]}

    with patch.object(gateway._client, "post", return_value=mock_response) as mock_post:
        vector = gateway.embed("本地模型")

    assert vector == [0.1, 0.2]
    assert "Authorization" not in mock_post.call_args.kwargs["headers"]


def test_resolve_provider_base_url_supports_ollama_env_override(monkeypatch) -> None:
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434")

    base_url = _resolve_provider_base_url("ollama", "", {"openai": "https://api.openai.com/v1"})

    assert base_url == "http://127.0.0.1:11434/v1"
