from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from fastembed import TextEmbedding
from qdrant_client import QdrantClient, models


DENSE_VECTOR_NAME = "dense"
SPARSE_VECTOR_NAME = "langchain-sparse"


@dataclass(frozen=True)
class QdrantSettings:
    url: str
    api_key: str
    collection: str
    prefer_grpc: bool
    timeout_seconds: float
    fastembed_model_name: str
    fastembed_sparse_model_name: str
    fastembed_vector_size: int
    fastembed_threads: int
    fastembed_cache_dir: str
    index_batch_size: int


def load_qdrant_settings(prefix: str = "QDRANT") -> QdrantSettings:
    timeout_raw = os.getenv(f"{prefix}_TIMEOUT_SECONDS", "10").strip()
    try:
        timeout_seconds = max(float(timeout_raw), 1.0)
    except ValueError:
        timeout_seconds = 10.0

    threads_raw = os.getenv("FASTEMBED_THREADS", "4").strip()
    try:
        fastembed_threads = max(int(threads_raw), 1)
    except ValueError:
        fastembed_threads = 4

    vector_size_raw = os.getenv("FASTEMBED_VECTOR_SIZE", "").strip()
    try:
        fastembed_vector_size = max(int(vector_size_raw), 0) if vector_size_raw else 0
    except ValueError:
        fastembed_vector_size = 0

    batch_size_raw = os.getenv("FASTEMBED_BATCH_SIZE", "64").strip()
    try:
        index_batch_size = max(int(batch_size_raw), 1)
    except ValueError:
        index_batch_size = 64

    return QdrantSettings(
        url=os.getenv(f"{prefix}_URL", "http://qdrant:6333").strip() or "http://qdrant:6333",
        api_key=os.getenv(f"{prefix}_API_KEY", "").strip(),
        collection=os.getenv(f"{prefix}_COLLECTION", "kb-evidence").strip() or "kb-evidence",
        prefer_grpc=os.getenv(f"{prefix}_PREFER_GRPC", "false").strip().lower() in {"1", "true", "yes", "on"},
        timeout_seconds=timeout_seconds,
        fastembed_model_name=os.getenv("FASTEMBED_MODEL_NAME", "BAAI/bge-small-zh-v1.5").strip() or "BAAI/bge-small-zh-v1.5",
        fastembed_sparse_model_name=os.getenv("FASTEMBED_SPARSE_MODEL_NAME", "Qdrant/bm25").strip() or "Qdrant/bm25",
        fastembed_vector_size=fastembed_vector_size,
        fastembed_threads=fastembed_threads,
        fastembed_cache_dir=os.getenv("FASTEMBED_CACHE_DIR", "").strip(),
        index_batch_size=index_batch_size,
    )


def qdrant_point_id(*, unit_type: str, unit_id: str) -> str:
    return str(uuid5(NAMESPACE_URL, f"qdrant-point:{unit_type}:{unit_id}"))


def dense_vector_size(settings: QdrantSettings | None = None) -> int:
    config = settings or load_qdrant_settings()
    if config.fastembed_vector_size > 0:
        return config.fastembed_vector_size
    for item in TextEmbedding.list_supported_models():
        if str(item.get("model") or "") == config.fastembed_model_name:
            return int(item.get("dim") or 0)
    raise RuntimeError(f"unsupported FASTEMBED_MODEL_NAME: {config.fastembed_model_name}")


def get_qdrant_client(settings: QdrantSettings | None = None) -> QdrantClient:
    config = settings or load_qdrant_settings()
    return _get_qdrant_client_cached(
        config.url,
        config.api_key,
        config.prefer_grpc,
        config.timeout_seconds,
    )


@lru_cache(maxsize=2)
def _get_qdrant_client_cached(url: str, api_key: str, prefer_grpc: bool, timeout_seconds: float) -> QdrantClient:
    return QdrantClient(
        url=url,
        api_key=api_key or None,
        prefer_grpc=prefer_grpc,
        timeout=timeout_seconds,
    )


def ensure_qdrant_collection(
    *,
    client: QdrantClient | None = None,
    settings: QdrantSettings | None = None,
) -> dict[str, Any]:
    config = settings or load_qdrant_settings()
    qdrant = client or get_qdrant_client(config)
    size = dense_vector_size(config)
    if not qdrant.collection_exists(config.collection):
        qdrant.create_collection(
            collection_name=config.collection,
            vectors_config={
                DENSE_VECTOR_NAME: models.VectorParams(
                    size=size,
                    distance=models.Distance.COSINE,
                )
            },
            sparse_vectors_config={
                SPARSE_VECTOR_NAME: models.SparseVectorParams(),
            },
        )
    for field_name in (
        "base_id",
        "document_id",
        "unit_type",
        "source_kind",
        "metadata.base_id",
        "metadata.document_id",
        "metadata.unit_type",
        "metadata.source_kind",
    ):
        qdrant.create_payload_index(
            config.collection,
            field_name=field_name,
            field_schema=models.PayloadSchemaType.KEYWORD,
        )
    return {
        "url": config.url,
        "collection": config.collection,
        "vector_name": DENSE_VECTOR_NAME,
        "sparse_vector_name": SPARSE_VECTOR_NAME,
        "vector_size": size,
        "model": config.fastembed_model_name,
        "sparse_model": config.fastembed_sparse_model_name,
    }


def check_qdrant_access(
    *,
    client: QdrantClient | None = None,
    settings: QdrantSettings | None = None,
) -> dict[str, Any]:
    config = settings or load_qdrant_settings()
    qdrant = client or get_qdrant_client(config)
    info = qdrant.get_collection(config.collection)
    return {
        "collection": config.collection,
        "status": str(getattr(info, "status", "") or "ok"),
    }


def embed_passages(texts: list[str], settings: QdrantSettings | None = None) -> list[list[float]]:
    if not texts:
        return []
    model = _get_fastembed_model(settings or load_qdrant_settings())
    return [_vector_to_list(item) for item in model.passage_embed(texts)]


def embed_query(text: str, settings: QdrantSettings | None = None) -> list[float]:
    cleaned = (text or "").strip()
    if not cleaned:
        return []
    model = _get_fastembed_model(settings or load_qdrant_settings())
    for item in model.query_embed(cleaned):
        return _vector_to_list(item)
    return []


@lru_cache(maxsize=2)
def _get_fastembed_model(settings: QdrantSettings) -> TextEmbedding:
    return TextEmbedding(
        model_name=settings.fastembed_model_name,
        cache_dir=settings.fastembed_cache_dir or None,
        threads=settings.fastembed_threads,
    )


def _vector_to_list(value: Any) -> list[float]:
    if hasattr(value, "tolist"):
        return [float(item) for item in value.tolist()]
    return [float(item) for item in list(value)]
