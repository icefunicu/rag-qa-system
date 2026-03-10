from __future__ import annotations

import time
from typing import Any

from langchain_core.documents import Document
from langchain_core.retrievers import BaseRetriever
from langchain_core.runnables import RunnableLambda
from pydantic import ConfigDict
from shared.logging import setup_logging
from shared.query_rewrite import rewrite_query
from shared.rerank import rerank_evidence_blocks
from shared.retrieval import EvidenceBlock, EvidencePath, RetrievalResult, RetrievalStats, weighted_rrf
from shared.text_search import build_simple_tsquery

from .query import compact_quote
from .runtime import db
from .vector_store import search_vector_documents


logger = setup_logging("kb-retrieve")
FUSION_WEIGHTS = {
    "structure": 1.3,
    "fts": 1.0,
    "vector": 0.9,
}


class StructureRetriever(BaseRetriever):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    base_id: str
    document_ids: list[str]
    focus_query: str
    limit: int = 20

    def _get_relevant_documents(self, query: str, *, run_manager: Any) -> list[Document]:
        cleaned = self.focus_query.strip() or query.strip()
        if not cleaned or not self.document_ids:
            return []
        with db.connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT
                        c.id AS unit_id,
                        d.base_id::text AS base_id,
                        c.document_id,
                        d.file_name AS document_title,
                        s.title AS section_title,
                        c.source_kind,
                        c.page_number,
                        c.asset_id::text AS asset_id,
                        c.char_start,
                        c.char_end,
                        c.text_content,
                        (
                            CASE WHEN lower(s.title) = lower(%s) THEN 8 ELSE 0 END
                            + CASE WHEN lower(s.title) LIKE lower(%s) THEN 4 ELSE 0 END
                            + CASE WHEN position(lower(%s) in lower(c.text_content)) > 0 THEN 2 ELSE 0 END
                        ) AS structure_score
                    FROM kb_chunks c
                    JOIN kb_sections s ON s.id = c.section_id
                    JOIN kb_documents d ON d.id = c.document_id
                    WHERE d.base_id = %s
                      AND d.query_ready = TRUE
                      AND c.document_id = ANY(%s::uuid[])
                      AND (
                          lower(s.title) = lower(%s)
                          OR lower(s.title) LIKE lower(%s)
                          OR position(lower(%s) in lower(c.text_content)) > 0
                      )
                    ORDER BY structure_score DESC, c.section_index ASC, c.chunk_index ASC
                    LIMIT %s
                    """,
                    (
                        cleaned,
                        f"%{cleaned}%",
                        cleaned,
                        self.base_id,
                        self.document_ids,
                        cleaned,
                        f"%{cleaned}%",
                        cleaned,
                        self.limit,
                    ),
                )
                rows = cur.fetchall()
        return [_row_to_document(row, signal_name="structure", score_key="structure_score") for row in rows]


class FTSRetriever(BaseRetriever):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    base_id: str
    document_ids: list[str]
    tsquery: str
    limit: int = 80

    def _get_relevant_documents(self, query: str, *, run_manager: Any) -> list[Document]:
        if not self.tsquery or not self.document_ids:
            return []
        with db.connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    WITH query AS (
                        SELECT to_tsquery('simple', %s) AS tsq
                    )
                    SELECT
                        c.id AS unit_id,
                        d.base_id::text AS base_id,
                        c.document_id,
                        d.file_name AS document_title,
                        s.title AS section_title,
                        c.source_kind,
                        c.page_number,
                        c.asset_id::text AS asset_id,
                        c.char_start,
                        c.char_end,
                        c.text_content,
                        ts_rank_cd(c.fts_document, query.tsq) AS fts_score
                    FROM kb_chunks c
                    JOIN kb_sections s ON s.id = c.section_id
                    JOIN kb_documents d ON d.id = c.document_id
                    JOIN query ON TRUE
                    WHERE d.base_id = %s
                      AND d.query_ready = TRUE
                      AND c.document_id = ANY(%s::uuid[])
                      AND c.fts_document @@ query.tsq
                    ORDER BY fts_score DESC, c.section_index ASC, c.chunk_index ASC
                    LIMIT %s
                    """,
                    (self.tsquery, self.base_id, self.document_ids, self.limit),
                )
                rows = cur.fetchall()
        return [_row_to_document(row, signal_name="fts", score_key="fts_score") for row in rows]


def retrieve_kb_evidence(
    *,
    base_id: str,
    question: str,
    document_ids: list[str] | None = None,
    limit: int = 8,
) -> list[EvidenceBlock]:
    return retrieve_kb_result(
        base_id=base_id,
        question=question,
        document_ids=document_ids,
        limit=limit,
    ).items


def retrieve_kb_result(
    *,
    base_id: str,
    question: str,
    document_ids: list[str] | None = None,
    limit: int = 8,
) -> RetrievalResult:
    chain = RunnableLambda(_prepare_request) | RunnableLambda(_run_signal_retrievers) | RunnableLambda(_fuse_and_rerank)
    return chain.invoke(
        {
            "base_id": base_id,
            "question": question,
            "document_ids": list(document_ids or []),
            "limit": limit,
        }
    )


def _prepare_request(payload: dict[str, Any]) -> dict[str, Any]:
    started = time.perf_counter()
    base_id = str(payload["base_id"])
    question = str(payload["question"])
    limit = int(payload["limit"])
    rewrite = rewrite_query(question)
    doc_ids = _resolve_document_ids(base_id=base_id, document_ids=list(payload.get("document_ids") or []))
    return {
        "started": started,
        "base_id": base_id,
        "question": question,
        "limit": limit,
        "rewrite": rewrite,
        "doc_ids": doc_ids,
    }


def _run_signal_retrievers(state: dict[str, Any]) -> dict[str, Any]:
    rewrite = state["rewrite"]
    doc_ids = list(state["doc_ids"])
    if not doc_ids:
        state["signal_documents"] = {"structure": [], "fts": [], "vector": []}
        state["degraded_signals"] = []
        state["warnings"] = []
        return state

    tsquery = build_simple_tsquery(rewrite.retrieval_query)
    structure_docs = StructureRetriever(
        base_id=state["base_id"],
        document_ids=doc_ids,
        focus_query=rewrite.focus_query or state["question"],
    ).invoke(rewrite.focus_query or state["question"])
    fts_docs = FTSRetriever(
        base_id=state["base_id"],
        document_ids=doc_ids,
        tsquery=tsquery,
    ).invoke(rewrite.retrieval_query)
    vector_docs, degraded_signals, warnings = search_vector_documents(
        base_id=state["base_id"],
        question=rewrite.retrieval_query,
        document_ids=doc_ids,
        limit=40,
    )
    state["signal_documents"] = {
        "structure": structure_docs,
        "fts": fts_docs,
        "vector": vector_docs,
    }
    state["degraded_signals"] = degraded_signals
    state["warnings"] = warnings
    return state


def _fuse_and_rerank(state: dict[str, Any]) -> RetrievalResult:
    rewrite = state["rewrite"]
    doc_ids = list(state["doc_ids"])
    if not doc_ids:
        return RetrievalResult(
            items=[],
            stats=RetrievalStats(
                original_query=rewrite.original_query,
                rewritten_query=rewrite.retrieval_query,
                focus_query=rewrite.focus_query,
                rewrite_tags=list(rewrite.strategy_tags),
                expansion_terms=list(rewrite.expansion_terms),
                retrieval_ms=round((time.perf_counter() - float(state["started"])) * 1000.0, 3),
            ),
        )

    signal_documents: dict[str, list[Document]] = dict(state.get("signal_documents") or {})
    results: dict[str, EvidenceBlock] = {}
    signal_lists: dict[str, list[str]] = {}

    for signal_name in ("structure", "fts", "vector"):
        _merge_documents(results, signal_lists, signal_documents.get(signal_name, []), signal_name)

    fused = weighted_rrf(signal_lists, weights=FUSION_WEIGHTS)
    ordered = sorted(fused.items(), key=lambda item: item[1], reverse=True)

    fused_blocks: list[EvidenceBlock] = []
    for final_rank, (unit_id, final_score) in enumerate(ordered, start=1):
        block = results[unit_id]
        fused_blocks.append(
            EvidenceBlock(
                unit_id=block.unit_id,
                document_id=block.document_id,
                document_title=block.document_title,
                section_title=block.section_title,
                chapter_title=block.chapter_title,
                scene_index=block.scene_index,
                char_range=block.char_range,
                quote=block.quote,
                raw_text=block.raw_text,
                corpus_id=block.corpus_id,
                corpus_type=block.corpus_type,
                service_type=block.service_type,
                evidence_kind=block.evidence_kind,
                source_kind=block.source_kind,
                page_number=block.page_number,
                asset_id=block.asset_id,
                thumbnail_url=block.thumbnail_url,
                signal_scores=dict(block.signal_scores),
                evidence_path=EvidencePath(
                    structure_hit="structure" in block.signal_scores,
                    fts_rank=_rank_of(signal_lists.get("fts", []), unit_id),
                    vector_rank=_rank_of(signal_lists.get("vector", []), unit_id),
                    final_rank=final_rank,
                    final_score=round(float(final_score), 6),
                ),
            )
        )

    rerank_pool = fused_blocks[: max(int(state["limit"]) * 3, 12)]
    reranked_blocks, rerank_debug = rerank_evidence_blocks(
        rewrite.focus_query or state["question"],
        rerank_pool,
        limit=int(state["limit"]),
    )
    debug_by_unit = {item.unit_id: item.score for item in rerank_debug}

    evidence: list[EvidenceBlock] = []
    for final_rank, block in enumerate(reranked_blocks, start=1):
        signal_scores = dict(block.signal_scores)
        if block.unit_id in debug_by_unit:
            signal_scores["rerank"] = debug_by_unit[block.unit_id]
        evidence.append(
            EvidenceBlock(
                unit_id=block.unit_id,
                document_id=block.document_id,
                document_title=block.document_title,
                section_title=block.section_title,
                chapter_title=block.chapter_title,
                scene_index=block.scene_index,
                char_range=block.char_range,
                quote=block.quote,
                raw_text=block.raw_text,
                corpus_id=block.corpus_id,
                corpus_type=block.corpus_type,
                service_type=block.service_type,
                evidence_kind=block.evidence_kind,
                source_kind=block.source_kind,
                page_number=block.page_number,
                asset_id=block.asset_id,
                thumbnail_url=block.thumbnail_url,
                signal_scores=signal_scores,
                evidence_path=EvidencePath(
                    structure_hit=block.evidence_path.structure_hit,
                    fts_rank=block.evidence_path.fts_rank,
                    vector_rank=block.evidence_path.vector_rank,
                    final_rank=final_rank,
                    final_score=block.evidence_path.final_score,
                ),
            )
        )

    stats = RetrievalStats(
        original_query=rewrite.original_query,
        rewritten_query=rewrite.retrieval_query,
        focus_query=rewrite.focus_query,
        rewrite_tags=list(rewrite.strategy_tags),
        expansion_terms=list(rewrite.expansion_terms),
        degraded_signals=list(state.get("degraded_signals") or []),
        warnings=list(state.get("warnings") or []),
        structure_candidates=len(dict.fromkeys(signal_lists.get("structure", []))),
        fts_candidates=len(dict.fromkeys(signal_lists.get("fts", []))),
        vector_candidates=len(dict.fromkeys(signal_lists.get("vector", []))),
        fused_candidates=len(fused_blocks),
        reranked_candidates=len(rerank_pool),
        selected_candidates=len(evidence),
        retrieval_ms=round((time.perf_counter() - float(state["started"])) * 1000.0, 3),
        rerank_applied=bool(rerank_pool),
    )
    return RetrievalResult(items=evidence, stats=stats)


def _resolve_document_ids(*, base_id: str, document_ids: list[str]) -> list[str]:
    with db.connect() as conn:
        with conn.cursor() as cur:
            if document_ids:
                cur.execute(
                    """
                    SELECT id::text
                    FROM kb_documents
                    WHERE base_id = %s
                      AND id = ANY(%s::uuid[])
                      AND query_ready = TRUE
                    ORDER BY created_at DESC
                    """,
                    (base_id, document_ids),
                )
            else:
                cur.execute(
                    """
                    SELECT id::text
                    FROM kb_documents
                    WHERE base_id = %s
                      AND query_ready = TRUE
                    ORDER BY created_at DESC
                    """,
                    (base_id,),
                )
            return [str(row["id"]) for row in cur.fetchall()]


def _row_to_document(row: dict[str, Any], *, signal_name: str, score_key: str) -> Document:
    asset_id = str(row.get("asset_id") or "")
    score = round(float(row.get(score_key) or 0.0), 6)
    return Document(
        page_content=str(row.get("text_content") or ""),
        metadata={
            "unit_id": str(row["unit_id"]),
            "document_id": str(row["document_id"]),
            "document_title": str(row.get("document_title") or ""),
            "section_title": str(row.get("section_title") or ""),
            "chapter_title": "",
            "scene_index": 0,
            "char_range": f"{row.get('char_start', 0)}-{row.get('char_end', 0)}",
            "quote": compact_quote(str(row.get("text_content") or ""), 180),
            "raw_text": str(row.get("text_content") or ""),
            "base_id": str(row.get("base_id") or ""),
            "source_kind": str(row.get("source_kind") or "text"),
            "page_number": int(row["page_number"]) if row.get("page_number") is not None else None,
            "asset_id": asset_id,
            "thumbnail_url": _thumbnail_url_from_asset_id(asset_id),
            "signal_scores": {signal_name: score},
            "evidence_path": {"structure_hit": signal_name == "structure"},
        },
    )


def _merge_documents(
    results: dict[str, EvidenceBlock],
    signal_lists: dict[str, list[str]],
    documents: list[Document],
    signal_name: str,
) -> None:
    signal_lists.setdefault(signal_name, [])
    for rank, document in enumerate(documents, start=1):
        metadata = dict(document.metadata or {})
        unit_id = str(metadata.get("unit_id") or "")
        if not unit_id:
            continue
        signal_lists[signal_name].append(unit_id)
        existing = results.get(unit_id)
        signal_scores = dict(existing.signal_scores) if existing else {}
        signal_scores.update(dict(metadata.get("signal_scores") or {}))
        evidence_path = dict(metadata.get("evidence_path") or {})
        if signal_name == "fts":
            evidence_path["fts_rank"] = rank
        if signal_name == "vector":
            evidence_path["vector_rank"] = int(evidence_path.get("vector_rank") or rank)
        results[unit_id] = EvidenceBlock(
            unit_id=unit_id,
            document_id=str(metadata.get("document_id") or ""),
            document_title=str(metadata.get("document_title") or ""),
            section_title=str(metadata.get("section_title") or ""),
            chapter_title=str(metadata.get("chapter_title") or ""),
            scene_index=int(metadata.get("scene_index") or 0),
            char_range=str(metadata.get("char_range") or ""),
            quote=str(metadata.get("quote") or ""),
            raw_text=str(metadata.get("raw_text") or document.page_content or ""),
            corpus_id=str(metadata.get("base_id") or (existing.corpus_id if existing else "")),
            corpus_type="kb",
            service_type="kb",
            evidence_kind="visual_ocr" if str(metadata.get("source_kind") or "") == "visual_ocr" else "text",
            source_kind=str(metadata.get("source_kind") or "text"),
            page_number=int(metadata["page_number"]) if metadata.get("page_number") is not None else None,
            asset_id=str(metadata.get("asset_id") or ""),
            thumbnail_url=str(metadata.get("thumbnail_url") or ""),
            signal_scores=signal_scores,
            evidence_path=EvidencePath(
                structure_hit=bool(evidence_path.get("structure_hit") or False),
                fts_rank=int(evidence_path["fts_rank"]) if evidence_path.get("fts_rank") is not None else existing.evidence_path.fts_rank if existing else None,
                vector_rank=int(evidence_path["vector_rank"]) if evidence_path.get("vector_rank") is not None else existing.evidence_path.vector_rank if existing else None,
            ),
        )


def _rank_of(items: list[str], unit_id: str) -> int | None:
    try:
        return items.index(unit_id) + 1
    except ValueError:
        return None


def _thumbnail_url_from_asset_id(asset_id: str) -> str:
    cleaned = asset_id.strip()
    if not cleaned:
        return ""
    return f"/api/v1/kb/visual-assets/{cleaned}/thumbnail"
