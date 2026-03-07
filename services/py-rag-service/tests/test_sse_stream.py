import json
from unittest.mock import MagicMock, patch

import pytest

from app.main import RAGEngine, Scope, ServiceConfig


@pytest.fixture
def mock_config():
    return ServiceConfig(
        postgres_dsn="postgres://rag:rag@localhost:5432/rag?sslmode=disable",
        qdrant_url="http://localhost:6333",
        qdrant_collection="rag_chunks",
        embedding_dim=256,
        retrieval_top_n=10,
        rerank_top_k=5,
        source_sentence_limit=3,
        evidence_min_score=0.05,
        common_knowledge_max_ratio=0.15,
        embedding_provider="openai",
        embedding_base_url="https://api.openai.com/v1",
        embedding_api_key="test-key",
        embedding_model="text-embedding-ada-002",
        chat_provider="openai",
        chat_base_url="https://api.openai.com/v1",
        chat_api_key="test-key",
        chat_model="gpt-3.5-turbo",
        llm_timeout_seconds=30,
        llm_max_retries=2,
        llm_retry_delay_milliseconds=600,
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


@pytest.fixture
def test_scope():
    return Scope(
        mode="single",
        corpus_ids=["550e8400-e29b-41d4-a716-446655440000"],
        document_ids=[],
        allow_common_knowledge=True,
    )


@pytest.fixture
def mock_llm():
    mock = MagicMock()
    mock.embed.return_value = [0.1] * 256
    mock.generate_summary.return_value = "这是测试答案"
    return mock


def _parse_sse_event(event_str: str) -> dict:
    if event_str.startswith("data: "):
        return json.loads(event_str[6:].strip())
    return json.loads(event_str.strip())


@pytest.mark.asyncio
async def test_query_stream_format(mock_config, test_scope, mock_llm):
    with patch("app.main.QdrantClient") as mock_qdrant, patch(
        "app.main.LLMGateway", return_value=mock_llm
    ):
        mock_qdrant_instance = MagicMock()
        mock_qdrant.return_value = mock_qdrant_instance

        mock_point = MagicMock()
        mock_point.id = "chunk-1"
        mock_point.score = 0.85
        mock_point.payload = {
            "document_id": "doc-1",
            "corpus_id": "corpus-1",
            "file_name": "test.txt",
            "page_or_loc": "page-1",
            "text": "这是测试文本",
        }
        mock_qdrant_instance.query_points.return_value = MagicMock(points=[mock_point])

        engine = RAGEngine(mock_config)
        engine._llm = mock_llm

        events = []
        async for event in engine.query_stream("测试问题", test_scope):
            events.append(event)

        assert len(events) > 0
        assert _parse_sse_event(events[-1])["type"] == "done"
        for event in events:
            assert event.endswith("\n\n")
            assert _parse_sse_event(event)["type"] in {"sentence", "citation", "done", "error"}


@pytest.mark.asyncio
async def test_query_stream_dense_failure_degrades_gracefully(mock_config, test_scope, mock_llm):
    with patch("app.main.QdrantClient") as mock_qdrant, patch(
        "app.main.LLMGateway", return_value=mock_llm
    ):
        mock_qdrant_instance = MagicMock()
        mock_qdrant.return_value = mock_qdrant_instance
        mock_qdrant_instance.query_points.side_effect = Exception("连接失败")

        engine = RAGEngine(mock_config)
        engine._llm = mock_llm

        events = []
        async for event in engine.query_stream("测试问题", test_scope):
            events.append(event)

        event_types = [_parse_sse_event(event)["type"] for event in events]
        assert "done" in event_types
        assert any(event_type in {"sentence", "error"} for event_type in event_types)


@pytest.mark.asyncio
async def test_query_stream_no_evidence(mock_config, test_scope, mock_llm):
    with patch("app.main.QdrantClient") as mock_qdrant, patch(
        "app.main.LLMGateway", return_value=mock_llm
    ):
        mock_qdrant_instance = MagicMock()
        mock_qdrant.return_value = mock_qdrant_instance
        mock_qdrant_instance.query_points.return_value = MagicMock(points=[])

        engine = RAGEngine(mock_config)
        engine._llm = mock_llm

        events = []
        async for event in engine.query_stream("测试问题", test_scope):
            events.append(event)

        event_types = [_parse_sse_event(event)["type"] for event in events]
        assert "sentence" in event_types
        assert "done" in event_types


def test_format_sse_output(mock_config, mock_llm):
    with patch("app.main.QdrantClient"), patch("app.main.LLMGateway", return_value=mock_llm):
        engine = RAGEngine(mock_config)

        event_str = engine._format_sse("sentence", {"text": "测试", "confidence": 0.9})
        assert event_str.endswith("\n\n")

        data = json.loads(event_str.strip().replace("data: ", ""))
        assert data["type"] == "sentence"
        assert data["data"]["text"] == "测试"
        assert data["data"]["confidence"] == 0.9

        event_done = engine._format_sse("done")
        data_done = json.loads(event_done.strip().replace("data: ", ""))
        assert data_done["type"] == "done"
        assert "data" not in data_done
