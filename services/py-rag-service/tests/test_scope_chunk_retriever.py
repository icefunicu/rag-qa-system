from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.hybrid_retriever import RetrievalResult
from app.main import RAGEngine, Scope, ServiceConfig
from app.scope_chunk_retriever import ScopeChunkRetriever


def _service_config(**overrides) -> ServiceConfig:
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
        embedding_provider="openai",
        embedding_base_url="https://api.openai.com/v1",
        embedding_api_key="test-key",
        embedding_model="text-embedding-3-small",
        chat_provider="openai",
        chat_base_url="https://api.openai.com/v1",
        chat_api_key="test-key",
        chat_model="gpt-4o-mini",
        llm_timeout_seconds=30,
        llm_max_retries=1,
        llm_retry_delay_milliseconds=0,
        hybrid_dense_weight=0.7,
        hybrid_sparse_weight=0.3,
        reranker_model="cross-encoder/ms-marco-MiniLM-L-6-v2",
        query_cache_enabled=False,
        query_cache_ttl_hours=24,
        query_cache_max_size=1000,
        sparse_retrieval_enabled=False,
        sparse_cache_ttl_seconds=600,
        sparse_cache_max_scopes=16,
        section_top_k=8,
        section_expand_chunk_limit=6,
        evidence_coverage_threshold=0.1,
        multi_query_enabled=False,
        multi_query_max_variants=3,
        multi_query_timeout_ms=500,
    )
    base.update(overrides)
    return ServiceConfig(**base)


def test_scope_chunk_retriever_search_uses_cache() -> None:
    retriever = ScopeChunkRetriever(
        "postgres://rag:rag@localhost:5432/rag?sslmode=disable",
        ttl_seconds=600,
        max_scopes=4,
    )
    scope = SimpleNamespace(
        mode="single",
        corpus_ids=["550e8400-e29b-41d4-a716-446655440000"],
        document_ids=[],
    )

    rows = [
        (
            "chunk-1",
            "550e8400-e29b-41d4-a716-446655440001",
            "550e8400-e29b-41d4-a716-446655440000",
            "test.txt",
            "text:1",
            "machine learning system",
            "doc:1:section:1",
            "第01章",
            5.2,
        ),
    ]
    mock_cursor = MagicMock()
    mock_cursor.fetchall.return_value = rows
    mock_conn = MagicMock()
    mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

    with patch("app.scope_chunk_retriever.psycopg.connect") as mock_connect:
        mock_connect.return_value = mock_conn
        first = retriever.search("machine learning", scope, top_k=5)
        second = retriever.search("machine learning", scope, top_k=5)

    assert mock_connect.call_count == 1
    assert first[0].section_id == "doc:1:section:1"
    assert second[0].retrieval_type == "sparse"


def test_scope_chunk_retriever_search_sections_returns_section_candidates() -> None:
    retriever = ScopeChunkRetriever("postgres://rag:rag@localhost:5432/rag?sslmode=disable")
    scope = SimpleNamespace(
        mode="single",
        corpus_ids=["550e8400-e29b-41d4-a716-446655440000"],
        document_ids=[],
    )

    rows = [
        (
            "doc:1:section:1",
            "550e8400-e29b-41d4-a716-446655440001",
            "550e8400-e29b-41d4-a716-446655440000",
            "test.txt",
            "text:1",
            "第01章",
            "第一章概要",
            7.1,
        ),
    ]
    mock_cursor = MagicMock()
    mock_cursor.fetchall.return_value = rows
    mock_conn = MagicMock()
    mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

    with patch("app.scope_chunk_retriever.psycopg.connect") as mock_connect:
        mock_connect.return_value = mock_conn
        results = retriever.search_sections("第01章讲了什么", scope, top_k=3)

    assert len(results) == 1
    assert results[0].section_title == "第01章"


@patch("app.main.QdrantClient")
def test_rag_engine_returns_grounded_extractive_answer(mock_qdrant) -> None:
    mock_qdrant.return_value = MagicMock()
    engine = RAGEngine(_service_config())
    engine._retrieve_dense_results = MagicMock(return_value=[])
    engine._retrieve_sparse_results = MagicMock(
        return_value=[
            RetrievalResult(
                chunk_id="chunk-1",
                document_id="doc-1",
                corpus_id="550e8400-e29b-41d4-a716-446655440000",
                file_name="test.txt",
                page_or_loc="text:1",
                text="Machine learning systems rely on high-quality training data.",
                score=12.0,
                retrieval_type="sparse",
                section_id="doc-1:section:1",
                section_title="第01章",
            )
        ]
    )
    engine._intent_classifier = MagicMock()
    engine._intent_classifier.classify_and_get_strategy.return_value = {
        "intent": "factual",
        "confidence": 0.9,
        "reason": "test",
        "strategy": {
            "top_k": 5,
            "rerank_top_k": 3,
            "dense_weight": 0.7,
            "sparse_weight": 0.3,
        },
    }
    engine._llm.generate_summary = MagicMock(return_value="")

    scope = Scope(
        mode="single",
        corpus_ids=["550e8400-e29b-41d4-a716-446655440000"],
        document_ids=[],
        allow_common_knowledge=False,
    )

    response = engine.query("What does the system rely on?", scope, debug=True)

    assert len(response.citations) == 1
    assert response.answer_mode == "extractive"
    assert response.evidence_coverage is not None
    assert response.citations[0].section_title == "第01章"
    assert response.debug_bundle is not None


@patch("app.main.QdrantClient")
def test_rag_engine_cache_key_includes_debug_profile_and_revision(mock_qdrant) -> None:
    mock_qdrant.return_value = MagicMock()
    engine = RAGEngine(_service_config())
    scope = Scope(
        mode="single",
        corpus_ids=["550e8400-e29b-41d4-a716-446655440000"],
        document_ids=[],
        allow_common_knowledge=False,
    )

    key_a = engine._build_cache_key("q", scope, debug=False, retrieval_profile="chunk_hybrid", revision="r1")
    key_b = engine._build_cache_key("q", scope, debug=True, retrieval_profile="chunk_hybrid", revision="r1")
    key_c = engine._build_cache_key("q", scope, debug=False, retrieval_profile="section_first", revision="r2")

    assert key_a != key_b
    assert key_a != key_c
