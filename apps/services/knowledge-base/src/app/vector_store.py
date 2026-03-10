from __future__ import annotations

from functools import lru_cache
from typing import Any

from langchain_core.documents import Document
from langchain_core.retrievers import BaseRetriever
from langchain_community.embeddings import FastEmbedEmbeddings
from langchain_qdrant import FastEmbedSparse, QdrantVectorStore, RetrievalMode
from pydantic import ConfigDict
from qdrant_client import models
from shared.qdrant_store import (
    DENSE_VECTOR_NAME,
    SPARSE_VECTOR_NAME,
    QdrantSettings,
    check_qdrant_access,
    ensure_qdrant_collection,
    get_qdrant_client,
    load_qdrant_settings,
    qdrant_point_id,
)
from shared.retrieval import EvidenceBlock, EvidencePath

from .runtime import db


QDRANT_SETTINGS = load_qdrant_settings()
METADATA_PREFIX = "metadata."


class KnowledgeBaseRetriever(BaseRetriever):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    vector_store: QdrantVectorStore
    base_id: str
    document_ids: list[str]
    limit: int

    def _get_relevant_documents(self, query: str, *, run_manager: Any) -> list[Document]:
        cleaned = query.strip()
        if not cleaned:
            return []
        filter_must: list[models.Condition] = [
            models.FieldCondition(key=f"{METADATA_PREFIX}base_id", match=models.MatchValue(value=self.base_id)),
        ]
        filtered_document_ids = [item for item in self.document_ids if item.strip()]
        if filtered_document_ids:
            filter_must.append(
                models.FieldCondition(key=f"{METADATA_PREFIX}document_id", match=models.MatchAny(any=filtered_document_ids))
            )
        results = self.vector_store.similarity_search_with_score(
            cleaned,
            k=max(self.limit, 1),
            filter=models.Filter(must=filter_must),
        )
        documents: list[Document] = []
        for rank, (document, score) in enumerate(results, start=1):
            metadata = dict(document.metadata or {})
            signal_scores = dict(metadata.get("signal_scores") or {})
            signal_scores["vector"] = round(float(score or 0.0), 6)
            metadata["signal_scores"] = signal_scores
            metadata["evidence_path"] = {
                **dict(metadata.get("evidence_path") or {}),
                "vector_rank": rank,
                "final_rank": rank,
                "final_score": round(float(score or 0.0), 6),
            }
            documents.append(Document(page_content=document.page_content, metadata=metadata))
        return documents


def ensure_vector_store() -> dict[str, Any]:
    return ensure_qdrant_collection(settings=QDRANT_SETTINGS)


def check_vector_store() -> dict[str, Any]:
    return check_qdrant_access(settings=QDRANT_SETTINGS)


def delete_document_vectors(document_id: str) -> None:
    cleaned = document_id.strip()
    if not cleaned:
        return
    client = get_qdrant_client(QDRANT_SETTINGS)
    client.delete(
        QDRANT_SETTINGS.collection,
        points_selector=models.FilterSelector(
            filter=models.Filter(
                should=[
                    models.FieldCondition(key="document_id", match=models.MatchValue(value=cleaned)),
                    models.FieldCondition(key=f"{METADATA_PREFIX}document_id", match=models.MatchValue(value=cleaned)),
                ]
            )
        ),
        wait=True,
    )


def delete_base_vectors(base_id: str) -> None:
    cleaned = base_id.strip()
    if not cleaned:
        return
    client = get_qdrant_client(QDRANT_SETTINGS)
    client.delete(
        QDRANT_SETTINGS.collection,
        points_selector=models.FilterSelector(
            filter=models.Filter(
                should=[
                    models.FieldCondition(key="base_id", match=models.MatchValue(value=cleaned)),
                    models.FieldCondition(key=f"{METADATA_PREFIX}base_id", match=models.MatchValue(value=cleaned)),
                ]
            )
        ),
        wait=True,
    )


def index_document_sections(document_id: str) -> dict[str, Any]:
    rows = _load_section_rows(document_id)
    return _index_rows(rows, unit_type="section", settings=QDRANT_SETTINGS)


def index_document_chunks(document_id: str) -> dict[str, Any]:
    rows = _load_chunk_rows(document_id)
    return _index_rows(rows, unit_type="chunk", settings=QDRANT_SETTINGS)


def build_vector_retriever(
    *,
    base_id: str,
    document_ids: list[str] | None,
    limit: int,
) -> KnowledgeBaseRetriever:
    ensure_qdrant_collection(settings=QDRANT_SETTINGS)
    return KnowledgeBaseRetriever(
        vector_store=_get_vector_store(QDRANT_SETTINGS),
        base_id=base_id,
        document_ids=[item for item in (document_ids or []) if item.strip()],
        limit=limit,
    )


def search_vector_documents(
    *,
    base_id: str,
    question: str,
    document_ids: list[str] | None,
    limit: int,
) -> tuple[list[Document], list[str], list[str]]:
    cleaned = question.strip()
    if not cleaned:
        return [], [], []
    try:
        retriever = build_vector_retriever(base_id=base_id, document_ids=document_ids, limit=limit)
        return retriever.invoke(cleaned), [], []
    except Exception:
        from .kb_runtime import logger

        logger.warning("qdrant vector retrieval degraded because query execution failed", exc_info=True)
        return [], ["vector"], ["vector retrieval disabled because qdrant query execution failed"]


def search_vector_evidence(
    *,
    base_id: str,
    question: str,
    document_ids: list[str] | None,
    limit: int,
) -> tuple[list[EvidenceBlock], list[str], list[str]]:
    documents, degraded_signals, warnings = search_vector_documents(
        base_id=base_id,
        question=question,
        document_ids=document_ids,
        limit=limit,
    )
    return [_document_to_evidence(item) for item in documents], degraded_signals, warnings


def _index_rows(rows: list[dict[str, Any]], *, unit_type: str, settings: QdrantSettings) -> dict[str, Any]:
    if not rows:
        return {
            "rows": 0,
            "indexed": 0,
            "collection": settings.collection,
            "model": settings.fastembed_model_name,
            "sparse_model": settings.fastembed_sparse_model_name,
            "retrieval_mode": RetrievalMode.HYBRID.value,
        }
    ensure_qdrant_collection(settings=settings)
    store = _get_vector_store(settings)
    documents = [_row_to_document(row, unit_type=unit_type) for row in rows]
    ids = [qdrant_point_id(unit_type=unit_type, unit_id=str(row["unit_id"])) for row in rows]
    batch_size = settings.index_batch_size
    indexed = 0
    for start in range(0, len(documents), batch_size):
        batch_documents = documents[start : start + batch_size]
        batch_ids = ids[start : start + batch_size]
        store.add_documents(batch_documents, ids=batch_ids)
        indexed += len(batch_documents)
    return {
        "rows": len(rows),
        "indexed": indexed,
        "collection": settings.collection,
        "model": settings.fastembed_model_name,
        "sparse_model": settings.fastembed_sparse_model_name,
        "retrieval_mode": RetrievalMode.HYBRID.value,
    }


def _row_to_document(row: dict[str, Any], *, unit_type: str) -> Document:
    asset_id = str(row.get("asset_id") or "")
    raw_text = str(row.get("raw_text") or "")
    embedding_text = str(row.get("embedding_text") or raw_text)
    metadata = {
        "unit_type": unit_type,
        "unit_id": str(row["unit_id"]),
        "base_id": str(row["base_id"]),
        "document_id": str(row["document_id"]),
        "document_title": str(row.get("document_title") or ""),
        "section_title": str(row.get("section_title") or ""),
        "chapter_title": str(row.get("chapter_title") or ""),
        "scene_index": int(row.get("scene_index") or 0),
        "char_range": str(row.get("char_range") or ""),
        "quote": str(row.get("quote") or ""),
        "raw_text": raw_text,
        "source_kind": str(row.get("source_kind") or "text"),
        "page_number": int(row["page_number"]) if row.get("page_number") is not None else None,
        "asset_id": asset_id,
        "thumbnail_url": _thumbnail_url_from_asset_id(asset_id),
        "signal_scores": {},
        "evidence_path": {},
    }
    return Document(page_content=embedding_text, metadata=metadata)


def _document_to_evidence(document: Document) -> EvidenceBlock:
    metadata = dict(document.metadata or {})
    evidence_path = dict(metadata.get("evidence_path") or {})
    return EvidenceBlock(
        unit_id=str(metadata.get("unit_id") or ""),
        document_id=str(metadata.get("document_id") or ""),
        document_title=str(metadata.get("document_title") or ""),
        section_title=str(metadata.get("section_title") or ""),
        chapter_title=str(metadata.get("chapter_title") or ""),
        scene_index=int(metadata.get("scene_index") or 0),
        char_range=str(metadata.get("char_range") or ""),
        quote=str(metadata.get("quote") or ""),
        raw_text=str(metadata.get("raw_text") or document.page_content or ""),
        corpus_id=str(metadata.get("base_id") or ""),
        corpus_type="kb",
        service_type="kb",
        evidence_kind="visual_ocr" if str(metadata.get("source_kind") or "") == "visual_ocr" else "text",
        source_kind=str(metadata.get("source_kind") or "text"),
        page_number=int(metadata["page_number"]) if metadata.get("page_number") is not None else None,
        asset_id=str(metadata.get("asset_id") or ""),
        thumbnail_url=str(metadata.get("thumbnail_url") or ""),
        signal_scores=dict(metadata.get("signal_scores") or {}),
        evidence_path=EvidencePath(
            structure_hit=bool(evidence_path.get("structure_hit") or False),
            fts_rank=int(evidence_path["fts_rank"]) if evidence_path.get("fts_rank") is not None else None,
            vector_rank=int(evidence_path["vector_rank"]) if evidence_path.get("vector_rank") is not None else None,
            final_rank=int(evidence_path["final_rank"]) if evidence_path.get("final_rank") is not None else None,
            final_score=round(float(evidence_path.get("final_score") or 0.0), 6),
        ),
    )


@lru_cache(maxsize=2)
def _get_vector_store(settings: QdrantSettings) -> QdrantVectorStore:
    dense_embedding = FastEmbedEmbeddings(
        model_name=settings.fastembed_model_name,
        cache_dir=settings.fastembed_cache_dir or None,
        threads=settings.fastembed_threads,
    )
    sparse_embedding = FastEmbedSparse(
        model_name=settings.fastembed_sparse_model_name,
        cache_dir=settings.fastembed_cache_dir or None,
        threads=settings.fastembed_threads,
    )
    return QdrantVectorStore.from_existing_collection(
        collection_name=settings.collection,
        embedding=dense_embedding,
        sparse_embedding=sparse_embedding,
        retrieval_mode=RetrievalMode.HYBRID,
        url=settings.url,
        api_key=settings.api_key or None,
        prefer_grpc=settings.prefer_grpc,
        timeout=max(int(settings.timeout_seconds), 1),
        vector_name=DENSE_VECTOR_NAME,
        sparse_vector_name=SPARSE_VECTOR_NAME,
        content_payload_key="page_content",
        metadata_payload_key="metadata",
    )


def _load_section_rows(document_id: str) -> list[dict[str, Any]]:
    with db.connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    sections.id::text AS unit_id,
                    documents.base_id::text AS base_id,
                    sections.document_id::text AS document_id,
                    documents.file_name AS document_title,
                    sections.title AS section_title,
                    '' AS chapter_title,
                    0 AS scene_index,
                    CONCAT(sections.char_start, '-', sections.char_end) AS char_range,
                    sections.summary AS quote,
                    LEFT(sections.search_text, 4000) AS raw_text,
                    COALESCE(sections.summary, sections.search_text, sections.title) AS embedding_text,
                    sections.source_kind,
                    sections.page_number,
                    COALESCE(sections.asset_id::text, '') AS asset_id
                FROM kb_sections sections
                JOIN kb_documents documents ON documents.id = sections.document_id
                WHERE sections.document_id = %s::uuid
                ORDER BY sections.section_index ASC
                """,
                (document_id,),
            )
            return cur.fetchall()


def _load_chunk_rows(document_id: str) -> list[dict[str, Any]]:
    with db.connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    chunks.id::text AS unit_id,
                    documents.base_id::text AS base_id,
                    chunks.document_id::text AS document_id,
                    documents.file_name AS document_title,
                    sections.title AS section_title,
                    '' AS chapter_title,
                    0 AS scene_index,
                    CONCAT(chunks.char_start, '-', chunks.char_end) AS char_range,
                    LEFT(chunks.text_content, 180) AS quote,
                    chunks.text_content AS raw_text,
                    chunks.text_content AS embedding_text,
                    chunks.source_kind,
                    chunks.page_number,
                    COALESCE(chunks.asset_id::text, '') AS asset_id
                FROM kb_chunks chunks
                JOIN kb_sections sections ON sections.id = chunks.section_id
                JOIN kb_documents documents ON documents.id = chunks.document_id
                WHERE chunks.document_id = %s::uuid
                ORDER BY chunks.section_index ASC, chunks.chunk_index ASC
                """,
                (document_id,),
            )
            return cur.fetchall()


def _thumbnail_url_from_asset_id(asset_id: str) -> str:
    cleaned = asset_id.strip()
    if not cleaned:
        return ""
    return f"/api/v1/kb/visual-assets/{cleaned}/thumbnail"
