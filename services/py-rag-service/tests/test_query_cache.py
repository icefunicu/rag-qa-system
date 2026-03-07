import time

from app.query_cache import CachedQuery, QueryCache


def test_cache_returns_deep_copy() -> None:
    cache = QueryCache(max_size=10, ttl_hours=1)
    result = {"answer": {"text": "value"}}

    cache.set("question", result)
    cached = cache.get("question")
    cached["answer"]["text"] = "mutated"

    again = cache.get("question")
    assert again["answer"]["text"] == "value"


def test_cache_supports_document_invalidation() -> None:
    cache = QueryCache(max_size=10, ttl_hours=1)
    cache.set("q1", {"answer": "a1"}, document_refs=["doc-1"])
    cache.set("q2", {"answer": "a2"}, document_refs=["doc-2"])

    removed = cache.invalidate_documents(["doc-1"])

    assert removed == 1
    assert cache.get("q1") is None
    assert cache.get("q2") == {"answer": "a2"}


def test_cache_ttl_expiration() -> None:
    cache = QueryCache(max_size=10, ttl_hours=1)
    cache._ttl_seconds = 1
    cache.set("question", {"answer": "answer"})

    time.sleep(2)

    assert cache.get("question") is None


def test_cached_query_is_expired() -> None:
    cached = CachedQuery(
        query_hash="hash",
        question="question",
        result={"answer": "x"},
        created_at=time.time() - 7200,
        ttl_seconds=3600,
    )

    assert cached.is_expired() is True
