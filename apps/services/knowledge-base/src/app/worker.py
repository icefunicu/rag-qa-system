from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx
from shared.logging import setup_logging
from shared.metrics import Counter, Histogram, start_http_server
from shared.text_encoding import detect_text_encoding
from shared.text_search import build_fts_lexeme_text

from .parsing import KBChunk, KBSection, ParsedKB, TXT_HEADING_RE, parse_document
from .runtime import BLOB_ROOT, db, prepare_runtime, storage
from .vector_store import (
    delete_document_vectors,
    index_document_chunks,
    index_document_sections,
)
from .vision import build_thumbnail, extract_visual_assets, load_vision_settings, run_ocr


logger = setup_logging("kb-worker")
POLL_SECONDS = float(os.getenv("KB_WORKER_POLL_SECONDS", "2"))
SECTION_BATCH_SIZE = int(os.getenv("KB_SECTION_BATCH_SIZE", "50"))
CHUNK_BATCH_SIZE = int(os.getenv("KB_CHUNK_BATCH_SIZE", "500"))
MAX_ATTEMPTS = max(int(os.getenv("KB_INGEST_MAX_ATTEMPTS", "5")), 1)
LEASE_SECONDS = max(int(os.getenv("KB_WORKER_LEASE_SECONDS", "300")), 30)
WORKER_METRICS_PORT = max(int(os.getenv("KB_WORKER_METRICS_PORT", "9300")), 0)
RETRY_DELAYS_SECONDS = (5, 15, 45, 135, 300)
VISION_SETTINGS = load_vision_settings()

WORKER_INGEST_ATTEMPTS_TOTAL = Counter("rag_kb_ingest_attempts_total", "KB worker ingest attempt outcomes.", labelnames=("outcome",))
WORKER_INGEST_PHASE_DURATION_MS = Histogram(
    "rag_kb_ingest_phase_duration_ms",
    "KB worker phase duration in milliseconds.",
    labelnames=("phase",),
    buckets=(10, 25, 50, 100, 250, 500, 1000, 2000, 5000, 15000, 30000),
)
WORKER_DEAD_LETTER_TOTAL = Counter("rag_kb_dead_letter_total_worker", "KB worker dead-lettered ingest jobs.")


def run_forever() -> None:
    prepare_runtime()
    if WORKER_METRICS_PORT > 0:
        start_http_server(WORKER_METRICS_PORT)
        logger.info("kb worker metrics listening port=%s", WORKER_METRICS_PORT)
    logger.info("kb worker started poll_seconds=%s", POLL_SECONDS)
    while True:
        job = _claim_next_job()
        if job is None:
            time.sleep(POLL_SECONDS)
            continue
        try:
            _process_job(job)
        except Exception as exc:  # pragma: no cover
            logger.exception("kb ingest job failed job_id=%s", job["id"])
            _handle_job_failure(job, exc)


def _claim_next_job() -> dict[str, Any] | None:
    lease_token = str(uuid4())
    with db.connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                WITH picked AS (
                    SELECT id
                    FROM kb_ingest_jobs
                    WHERE (
                        status IN ('queued', 'retry')
                        AND COALESCE(next_retry_at, created_at) <= NOW()
                    )
                    OR (
                        status = 'processing'
                        AND lease_expires_at IS NOT NULL
                        AND lease_expires_at <= NOW()
                    )
                    ORDER BY COALESCE(next_retry_at, created_at) ASC, created_at ASC
                    FOR UPDATE SKIP LOCKED
                    LIMIT 1
                )
                UPDATE kb_ingest_jobs AS jobs
                SET status = 'processing',
                    started_at = COALESCE(started_at, NOW()),
                    attempt_count = COALESCE(jobs.attempt_count, 0) + 1,
                    max_attempts = CASE WHEN COALESCE(jobs.max_attempts, 0) > 0 THEN jobs.max_attempts ELSE %s END,
                    lease_token = %s,
                    lease_expires_at = NOW() + (%s || ' seconds')::interval,
                    updated_at = NOW()
                FROM picked
                WHERE jobs.id = picked.id
                RETURNING jobs.*
                """,
                (MAX_ATTEMPTS, lease_token, LEASE_SECONDS),
            )
            row = cur.fetchone()
        conn.commit()
    return row


def _process_job(job: dict[str, Any]) -> None:
    trace_id = f"kb-job-{job['id']}"
    document_id = str(job["document_id"])
    document = _load_document(document_id)
    target_dir = BLOB_ROOT / document_id
    target_dir.mkdir(parents=True, exist_ok=True)
    source_path = target_dir / (document.get("file_name") or "source.bin")

    storage.download_file(str(document["storage_key"]), source_path)
    _append_event(document_id, "uploaded", "object storage download complete", {"trace_id": trace_id})
    _update_job(str(job["id"]), phase="parsing_fast", checkpoint={"downloaded": True})
    _update_document(document_id, status="parsing_fast", query_ready=False, enhancement_status="fts_pending")
    _cleanup_visual_assets(document_id)
    delete_document_vectors(document_id)

    parse_started = time.perf_counter()
    file_type = str(document.get("file_type") or "").lower()
    text_stats = _index_txt_document(document_id=document_id, path=source_path) if file_type == "txt" else _index_binary_document(document_id=document_id, path=source_path, file_type=file_type)
    text_stats["parse_ms"] = round((time.perf_counter() - parse_started) * 1000.0, 3)
    WORKER_INGEST_PHASE_DURATION_MS.labels("parse").observe(float(text_stats["parse_ms"]))

    base_query_ready = int(text_stats.get("chunk_count") or 0) > 0
    _update_document(
        document_id,
        status="fast_index_ready" if base_query_ready else "enhancing",
        query_ready=base_query_ready,
        enhancement_status="fts_only" if base_query_ready else "visual_pending",
        query_ready_at=base_query_ready,
        section_count=int(text_stats.get("section_count") or 0),
        chunk_count=int(text_stats.get("chunk_count") or 0),
        stats=text_stats,
    )
    _update_job(
        str(job["id"]),
        phase="fast_index_ready" if base_query_ready else "visual_pending",
        query_ready=base_query_ready,
        enhancement_status="fts_only" if base_query_ready else "visual_pending",
        checkpoint=text_stats,
    )

    visual_started = time.perf_counter()
    visual_stats = _index_visual_assets(document_id=document_id, path=source_path, file_type=file_type)
    visual_stats["visual_ms"] = round((time.perf_counter() - visual_started) * 1000.0, 3)
    WORKER_INGEST_PHASE_DURATION_MS.labels("visual").observe(float(visual_stats["visual_ms"]))
    combined_stats = _merge_ingest_stats(text_stats, visual_stats)
    if int(combined_stats.get("chunk_count") or 0) <= 0:
        raise ValueError("document contains no extractable text or OCR content")

    _update_document(
        document_id,
        status="enhancing",
        query_ready=True,
        enhancement_status="visual_ready" if int(visual_stats.get("visual_asset_count") or 0) > 0 else "fts_only",
        query_ready_at=True,
        section_count=int(combined_stats.get("section_count") or 0),
        chunk_count=int(combined_stats.get("chunk_count") or 0),
        stats=combined_stats,
    )
    _update_job(str(job["id"]), phase="enhancing", query_ready=True, enhancement_status="visual_ready" if int(visual_stats.get("visual_asset_count") or 0) > 0 else "fts_only", checkpoint=combined_stats)

    section_embed_started = time.perf_counter()
    section_embed_stats = index_document_sections(document_id)
    section_embed_ms = round((time.perf_counter() - section_embed_started) * 1000.0, 3)
    _update_document(document_id, status="hybrid_ready", query_ready=True, enhancement_status="summary_vectors_ready", hybrid_ready_at=True, stats={"vector_index": {"sections": section_embed_stats}})
    _append_event(document_id, "hybrid_ready", "section vectors indexed in qdrant", {"trace_id": trace_id, "section_embed_ms": section_embed_ms, "vector_index": section_embed_stats})
    WORKER_INGEST_PHASE_DURATION_MS.labels("section_embed").observe(float(section_embed_ms))
    _update_job(str(job["id"]), phase="hybrid_ready", query_ready=True, enhancement_status="summary_vectors_ready")

    chunk_embed_started = time.perf_counter()
    chunk_embed_stats = index_document_chunks(document_id)
    chunk_embed_ms = round((time.perf_counter() - chunk_embed_started) * 1000.0, 3)
    _update_document(document_id, status="ready", query_ready=True, enhancement_status="chunk_vectors_ready", ready_at=True, stats={"vector_index": {"sections": section_embed_stats, "chunks": chunk_embed_stats}})
    _append_event(document_id, "ready", "chunk vectors indexed in qdrant", {"trace_id": trace_id, "chunk_embed_ms": chunk_embed_ms, "vector_index": chunk_embed_stats})
    WORKER_INGEST_PHASE_DURATION_MS.labels("chunk_embed").observe(float(chunk_embed_ms))
    _update_job(str(job["id"]), status="done", phase="ready", query_ready=True, enhancement_status="chunk_vectors_ready", finished=True)
    _append_audit_event(action="kb.ingest.complete", outcome="success", resource_type="ingest_job", resource_id=str(job["id"]), details={"document_id": document_id, "trace_id": trace_id})
    WORKER_INGEST_ATTEMPTS_TOTAL.labels("success").inc()


def _load_document(document_id: str) -> dict[str, Any]:
    with db.connect() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM kb_documents WHERE id = %s", (document_id,))
            row = cur.fetchone()
    if row is None:
        raise RuntimeError(f"kb document not found: {document_id}")
    return row


def _index_binary_document(*, document_id: str, path: Path, file_type: str) -> dict[str, Any]:
    parsed = parse_document(path, file_type)
    _replace_document_units(document_id, parsed)
    return {"section_count": len(parsed.sections), "chunk_count": len(parsed.chunks), "section_preview": _section_preview_from_sections(parsed.sections)}


def _index_txt_document(*, document_id: str, path: Path) -> dict[str, Any]:
    with db.connect() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM kb_chunks WHERE document_id = %s", (document_id,))
            cur.execute("DELETE FROM kb_sections WHERE document_id = %s", (document_id,))
        conn.commit()

    section_buffer: list[KBSection] = []
    chunk_buffer: list[KBChunk] = []
    section_total = 0
    chunk_total = 0
    query_opened = False
    current_title = "Section 1"
    current_lines: list[str] = []
    section_index = 1
    cursor = 0
    start = 0

    for raw in _iter_text_lines(path):
        stripped = raw.strip()
        is_heading = bool(stripped and TXT_HEADING_RE.match(stripped))
        if is_heading and current_lines:
            section, chunks = _build_section_and_chunks(section_index=section_index, title=current_title, raw_text="".join(current_lines), char_start=start)
            if section is not None:
                section_buffer.append(section)
                chunk_buffer.extend(chunks)
                section_total += 1
                chunk_total += len(chunks)
                section_index += 1
            current_title = stripped[:80]
            current_lines = [raw]
            start = cursor
        else:
            if not current_lines and stripped:
                start = cursor
            current_lines.append(raw)
        cursor += len(raw)

        if len(section_buffer) >= SECTION_BATCH_SIZE or len(chunk_buffer) >= CHUNK_BATCH_SIZE:
            _flush_txt_batch(document_id, section_buffer, chunk_buffer)
            if not query_opened and chunk_total > 0:
                query_opened = True
                _update_document(document_id, query_ready=True, query_ready_at=True)
                _append_event(document_id, "query_window_open", f"queryable after {section_total} sections")
            _update_job(_job_id_for_document(document_id), checkpoint={"section_count": section_total, "chunk_count": chunk_total})
            section_buffer = []
            chunk_buffer = []

    if current_lines:
        section, chunks = _build_section_and_chunks(section_index=section_index, title=current_title, raw_text="".join(current_lines), char_start=start)
        if section is not None:
            section_buffer.append(section)
            chunk_buffer.extend(chunks)
            section_total += 1
            chunk_total += len(chunks)

    if section_buffer or chunk_buffer:
        _flush_txt_batch(document_id, section_buffer, chunk_buffer)
        if not query_opened and chunk_total > 0:
            _update_document(document_id, query_ready=True, query_ready_at=True)
            _append_event(document_id, "query_window_open", f"queryable after {section_total} sections")

    return {"section_count": section_total, "chunk_count": chunk_total, "section_preview": _fetch_section_preview(document_id)}


def _iter_text_lines(path: Path):
    encoding = detect_text_encoding(path)
    with path.open("r", encoding=encoding, errors="replace") as handle:
        for raw in handle:
            yield raw


def _build_section_and_chunks(
    *,
    section_index: int,
    title: str,
    raw_text: str,
    char_start: int,
    source_kind: str = "text",
    page_number: int | None = None,
    asset_id: str | None = None,
) -> tuple[KBSection | None, list[KBChunk]]:
    content = raw_text.strip()
    if not content:
        return None, []
    section_id = str(uuid4())
    summary = _summary(content, 180)
    section = KBSection(
        id=section_id,
        section_index=section_index,
        title=title or f"Section {section_index}",
        summary=summary,
        search_text=" ".join([title, content[:600]]).strip(),
        text=content,
        char_start=char_start,
        char_end=char_start + len(content),
        source_kind=source_kind,
        page_number=page_number,
        asset_id=asset_id,
    )

    chunks: list[KBChunk] = []
    cursor = 0
    chunk_index = 1
    while cursor < len(content):
        end = min(cursor + 1000, len(content))
        snippet = content[cursor:end].strip()
        if snippet:
            chunks.append(KBChunk(id=str(uuid4()), section_id=section_id, section_index=section_index, chunk_index=chunk_index, text=snippet, search_text=snippet, char_start=char_start + cursor, char_end=char_start + end, source_kind=source_kind, page_number=page_number, asset_id=asset_id))
            chunk_index += 1
        if end >= len(content):
            break
        cursor = max(end - 120, cursor + 1)
    return section, chunks


def _flush_txt_batch(document_id: str, sections: list[KBSection], chunks: list[KBChunk]) -> None:
    with db.connect() as conn:
        with conn.cursor() as cur:
            _insert_sections(cur, document_id, sections)
            _insert_chunks(cur, document_id, chunks)
        conn.commit()


def _replace_document_units(document_id: str, parsed: ParsedKB) -> None:
    with db.connect() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM kb_chunks WHERE document_id = %s", (document_id,))
            cur.execute("DELETE FROM kb_sections WHERE document_id = %s", (document_id,))
            _insert_sections(cur, document_id, parsed.sections)
            _insert_chunks(cur, document_id, parsed.chunks)
        conn.commit()


def _index_visual_assets(*, document_id: str, path: Path, file_type: str) -> dict[str, Any]:
    visual_assets = extract_visual_assets(path, file_type, max_assets=VISION_SETTINGS.max_assets_per_document)
    if not visual_assets:
        return {"visual_asset_count": 0, "visual_ocr_chunk_count": 0, "visual_ocr_section_count": 0, "visual_provider": "", "section_preview": _fetch_section_preview(document_id)}

    asset_rows: list[dict[str, Any]] = []
    section_rows: list[KBSection] = []
    chunk_rows: list[KBChunk] = []
    section_index = _next_section_index(document_id)
    visual_provider = ""

    for asset in visual_assets:
        asset_id = asset.id
        file_suffix = Path(asset.file_name).suffix or _default_suffix_for_mime(asset.mime_type)
        storage_key = storage.build_storage_key(service="kb-visual", document_id=document_id, file_name=f"{asset.asset_index:04d}{file_suffix}")
        thumbnail_key = storage.build_storage_key(service="kb-visual-thumb", document_id=document_id, file_name=f"{asset.asset_index:04d}.jpg")
        storage.put_bytes(
            storage_key,
            asset.data,
            metadata={"document_id": document_id, "asset_id": asset_id},
            content_type=asset.mime_type,
        )
        thumbnail_bytes, thumbnail_content_type = build_thumbnail(asset.data, max_edge_px=VISION_SETTINGS.thumbnail_max_side)
        storage.put_bytes(
            thumbnail_key,
            thumbnail_bytes,
            metadata={"document_id": document_id, "asset_id": asset_id, "thumbnail": "true"},
            content_type=thumbnail_content_type,
        )

        ocr_result = None
        try:
            ocr_result = run_ocr(asset, VISION_SETTINGS)
        except Exception:
            logger.warning("visual OCR failed document_id=%s asset_index=%s", document_id, asset.asset_index, exc_info=True)
        if ocr_result and ocr_result.provider:
            visual_provider = visual_provider or ocr_result.provider

        asset_rows.append(
            {
                "id": asset_id,
                "document_id": document_id,
                "asset_index": asset.asset_index,
                "page_number": asset.page_number,
                "source_kind": asset.source_kind,
                "file_name": asset.file_name,
                "mime_type": asset.mime_type,
                "size_bytes": len(asset.data),
                "storage_key": storage_key,
                "thumbnail_key": thumbnail_key,
                "content_hash": asset.content_hash,
                "width": asset.width,
                "height": asset.height,
                "status": "ready" if ocr_result and ocr_result.text.strip() else "stored",
                "provider": ocr_result.provider if ocr_result else "",
                "ocr_text": ocr_result.text if ocr_result else "",
                "summary": ocr_result.summary if ocr_result else "",
            }
        )

        if not ocr_result or not ocr_result.text.strip():
            continue
        section, chunks = _build_section_and_chunks(section_index=section_index, title=f"Page {asset.page_number} screenshot {asset.asset_index}", raw_text=ocr_result.text, char_start=0, source_kind="visual_ocr", page_number=asset.page_number, asset_id=asset_id)
        if section is None:
            continue
        section_rows.append(section)
        chunk_rows.extend(chunks)
        section_index += 1

    with db.connect() as conn:
        with conn.cursor() as cur:
            if asset_rows:
                cur.executemany(
                    """
                    INSERT INTO kb_visual_assets (
                        id, document_id, asset_index, page_number, source_kind, file_name, mime_type,
                        storage_key, thumbnail_key, content_hash, width, height, size_bytes,
                        status, provider, ocr_text, summary
                    )
                    VALUES (
                        %s, %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, %s
                    )
                    """,
                    [
                        (
                            item["id"],
                            item["document_id"],
                            item["asset_index"],
                            item["page_number"],
                            item["source_kind"],
                            item["file_name"],
                            item["mime_type"],
                            item["storage_key"],
                            item["thumbnail_key"],
                            item["content_hash"],
                            item["width"],
                            item["height"],
                            item["size_bytes"],
                            item["status"],
                            item["provider"],
                            item["ocr_text"],
                            item["summary"],
                        )
                        for item in asset_rows
                    ],
                )
            _insert_sections(cur, document_id, section_rows)
            _insert_chunks(cur, document_id, chunk_rows)
        conn.commit()

    return {"visual_asset_count": len(asset_rows), "visual_ocr_chunk_count": len(chunk_rows), "visual_ocr_section_count": len(section_rows), "visual_provider": visual_provider, "section_preview": _fetch_section_preview(document_id)}


def _cleanup_visual_assets(document_id: str) -> None:
    with db.connect() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT storage_key, thumbnail_key FROM kb_visual_assets WHERE document_id = %s", (document_id,))
            rows = cur.fetchall()
            cur.execute("DELETE FROM kb_visual_assets WHERE document_id = %s", (document_id,))
        conn.commit()
    for row in rows:
        for key in (str(row.get("storage_key") or ""), str(row.get("thumbnail_key") or "")):
            if key:
                try:
                    storage.delete_object(key)
                except Exception:
                    logger.warning("failed to cleanup visual asset object document_id=%s", document_id, exc_info=True)


def _next_section_index(document_id: str) -> int:
    with db.connect() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COALESCE(MAX(section_index), 0) AS section_index FROM kb_sections WHERE document_id = %s", (document_id,))
            row = cur.fetchone()
    return int(row["section_index"] or 0) + 1 if row else 1


def _section_preview_from_sections(sections: list[KBSection], *, limit: int = 6) -> list[str]:
    return [item.summary or item.title for item in sections[:limit]]


def _fetch_section_preview(document_id: str, *, limit: int = 6) -> list[str]:
    with db.connect() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT summary, title FROM kb_sections WHERE document_id = %s ORDER BY section_index ASC LIMIT %s", (document_id, limit))
            rows = cur.fetchall()
    return [str(row.get("summary") or row.get("title") or "") for row in rows]


def _insert_sections(cur, document_id: str, sections: list[KBSection]) -> None:
    if not sections:
        return
    cur.executemany(
        """
        INSERT INTO kb_sections (
            id, document_id, section_index, title, summary, search_text,
            lexical_terms, fts_document, content_hash, char_start, char_end,
            source_kind, page_number, asset_id
        )
        VALUES (
            %s, %s, %s, %s, %s, %s,
            %s, to_tsvector('simple', %s), %s, %s, %s,
            %s, %s, %s
        )
        """,
        [
            (
                item.id,
                document_id,
                item.section_index,
                item.title,
                item.summary,
                item.search_text,
                build_fts_lexeme_text(item.title, item.summary, item.text[:1200]),
                build_fts_lexeme_text(item.title, item.summary, item.text[:1200]),
                _hash_text(item.text),
                item.char_start,
                item.char_end,
                item.source_kind,
                item.page_number,
                item.asset_id,
            )
            for item in sections
        ],
    )


def _insert_chunks(cur, document_id: str, chunks: list[KBChunk]) -> None:
    if not chunks:
        return
    cur.executemany(
        """
        INSERT INTO kb_chunks (
            id, document_id, section_id, section_index, chunk_index, text_content,
            search_text, lexical_terms, fts_document, content_hash, char_start, char_end,
            source_kind, page_number, asset_id
        )
        VALUES (
            %s, %s, %s, %s, %s, %s,
            %s, %s, to_tsvector('simple', %s), %s, %s, %s,
            %s, %s, %s
        )
        """,
        [(item.id, document_id, item.section_id, item.section_index, item.chunk_index, item.text, item.search_text, build_fts_lexeme_text(item.text[:1400]), build_fts_lexeme_text(item.text[:1400]), _hash_text(item.text), item.char_start, item.char_end, item.source_kind, item.page_number, item.asset_id) for item in chunks],
    )


def _update_job(job_id: str | None, *, status: str | None = None, phase: str | None = None, query_ready: bool | None = None, enhancement_status: str | None = None, checkpoint: dict[str, Any] | None = None, finished: bool = False) -> None:
    if not job_id:
        return
    with db.connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE kb_ingest_jobs
                SET status = COALESCE(%s, status),
                    phase = COALESCE(%s, phase),
                    query_ready = COALESCE(%s, query_ready),
                    enhancement_status = COALESCE(%s, enhancement_status),
                    checkpoint_json = COALESCE(%s::jsonb, checkpoint_json),
                    error_message = CASE WHEN %s THEN '' ELSE error_message END,
                    last_error_code = CASE WHEN %s THEN '' ELSE last_error_code END,
                    next_retry_at = CASE WHEN %s THEN NULL ELSE next_retry_at END,
                    lease_token = CASE WHEN %s THEN '' ELSE lease_token END,
                    lease_expires_at = CASE WHEN %s THEN NULL ELSE lease_expires_at END,
                    finished_at = CASE WHEN %s THEN NOW() ELSE finished_at END,
                    updated_at = NOW()
                WHERE id = %s
                """,
                (status, phase, query_ready, enhancement_status, _to_json(checkpoint) if checkpoint is not None else None, finished, finished, finished, finished, finished, finished, job_id),
            )
        conn.commit()


def _job_id_for_document(document_id: str) -> str | None:
    with db.connect() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id::text FROM kb_ingest_jobs WHERE document_id = %s ORDER BY created_at DESC LIMIT 1", (document_id,))
            row = cur.fetchone()
    return str(row["id"]) if row else None


def _update_document(document_id: str, *, status: str | None = None, query_ready: bool | None = None, enhancement_status: str | None = None, query_ready_at: bool = False, hybrid_ready_at: bool = False, ready_at: bool = False, section_count: int | None = None, chunk_count: int | None = None, stats: dict[str, Any] | None = None) -> None:
    with db.connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE kb_documents
                SET status = COALESCE(%s, status),
                    query_ready = COALESCE(%s, query_ready),
                    enhancement_status = COALESCE(%s, enhancement_status),
                    query_ready_at = CASE WHEN %s THEN COALESCE(query_ready_at, NOW()) ELSE query_ready_at END,
                    hybrid_ready_at = CASE WHEN %s THEN COALESCE(hybrid_ready_at, NOW()) ELSE hybrid_ready_at END,
                    ready_at = CASE WHEN %s THEN COALESCE(ready_at, NOW()) ELSE ready_at END,
                    section_count = COALESCE(%s, section_count),
                    chunk_count = COALESCE(%s, chunk_count),
                    stats_json = COALESCE(stats_json, '{}'::jsonb) || COALESCE(%s::jsonb, '{}'::jsonb),
                    updated_at = NOW()
                WHERE id = %s
                """,
                (status, query_ready, enhancement_status, query_ready_at, hybrid_ready_at, ready_at, section_count, chunk_count, _to_json(stats) if stats is not None else None, document_id),
            )
        conn.commit()


def _append_event(document_id: str, stage: str, message: str, details: dict[str, Any] | None = None) -> None:
    with db.connect() as conn:
        with conn.cursor() as cur:
            cur.execute("INSERT INTO kb_document_events (document_id, stage, message, details_json) VALUES (%s, %s, %s, %s::jsonb)", (document_id, stage, message, _to_json(details)))
        conn.commit()


def _append_audit_event(*, action: str, outcome: str, resource_type: str, resource_id: str, details: dict[str, Any] | None = None) -> None:
    try:
        with db.connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO kb_audit_events (
                        actor_user_id, actor_email, actor_role, action, resource_type,
                        resource_id, scope, outcome, trace_id, request_path, details_json
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)
                    """,
                    ("", "system", "system", action, resource_type, resource_id, "system", outcome, "", "kb-worker", _to_json(details)),
                )
            conn.commit()
    except Exception:
        logger.exception("kb worker audit write failed action=%s outcome=%s", action, outcome)


def _retry_delay_seconds(attempt_count: int) -> int:
    if attempt_count <= 0:
        return RETRY_DELAYS_SECONDS[0]
    return int(RETRY_DELAYS_SECONDS[min(attempt_count - 1, len(RETRY_DELAYS_SECONDS) - 1)])


def _classify_ingest_failure(exc: Exception) -> tuple[str, bool]:
    module_name = exc.__class__.__module__.lower()
    message = str(exc).lower()
    if isinstance(exc, (TimeoutError, ConnectionError, OSError, httpx.HTTPError)):
        return "transient_dependency_error", True
    if "botocore" in module_name or "boto3" in module_name:
        return "object_storage_error", True
    if "not found" in message or "missing" in message:
        return "missing_source", False
    if isinstance(exc, ValueError) or "unsupported" in message or "invalid" in message:
        return "invalid_document", False
    return "internal_error", True


def _schedule_job_retry(job: dict[str, Any], *, message: str, error_code: str, delay_seconds: int) -> None:
    job_id = str(job["id"])
    document_id = str(job["document_id"])
    with db.connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE kb_ingest_jobs
                SET status = 'retry',
                    phase = 'retry_wait',
                    checkpoint_json = %s::jsonb,
                    error_message = %s,
                    last_error_code = %s,
                    next_retry_at = NOW() + (%s || ' seconds')::interval,
                    lease_token = '',
                    lease_expires_at = NULL,
                    updated_at = NOW()
                WHERE id = %s
                """,
                (_to_json({"error": message, "retry_delay_seconds": delay_seconds}), message, error_code, delay_seconds, job_id),
            )
        conn.commit()
    _update_document(document_id, status="uploaded", query_ready=False, enhancement_status="retry_pending")
    _append_event(document_id, "uploaded", f"retry scheduled in {delay_seconds}s", {"job_id": job_id, "error_code": error_code, "attempt_count": int(job.get("attempt_count") or 0)})
    _append_audit_event(action="kb.ingest.retry_scheduled", outcome="retry", resource_type="ingest_job", resource_id=job_id, details={"document_id": document_id, "error": message, "error_code": error_code, "retry_delay_seconds": delay_seconds})
    WORKER_INGEST_ATTEMPTS_TOTAL.labels("retry").inc()


def _dead_letter_job(job: dict[str, Any], *, message: str, error_code: str) -> None:
    job_id = str(job["id"])
    document_id = str(job["document_id"])
    with db.connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE kb_ingest_jobs
                SET status = 'dead_letter',
                    phase = 'dead_letter',
                    checkpoint_json = %s::jsonb,
                    error_message = %s,
                    last_error_code = %s,
                    dead_lettered_at = NOW(),
                    finished_at = NOW(),
                    lease_token = '',
                    lease_expires_at = NULL,
                    updated_at = NOW()
                WHERE id = %s
                """,
                (_to_json({"error": message}), message, error_code, job_id),
            )
        conn.commit()
    _update_document(document_id, status="failed", query_ready=False, enhancement_status="failed")
    _append_event(document_id, "failed", message, {"job_id": job_id, "error_code": error_code})
    _append_audit_event(action="kb.ingest.dead_lettered", outcome="failed", resource_type="ingest_job", resource_id=job_id, details={"document_id": document_id, "error": message, "error_code": error_code})
    WORKER_INGEST_ATTEMPTS_TOTAL.labels("dead_letter").inc()
    WORKER_DEAD_LETTER_TOTAL.inc()


def _handle_job_failure(job: dict[str, Any], exc: Exception) -> None:
    message = str(exc)
    error_code, retryable = _classify_ingest_failure(exc)
    attempt_count = int(job.get("attempt_count") or 0)
    max_attempts = max(int(job.get("max_attempts") or MAX_ATTEMPTS), 1)
    if retryable and attempt_count < max_attempts:
        _schedule_job_retry(job, message=message, error_code=error_code, delay_seconds=_retry_delay_seconds(attempt_count))
        return
    _dead_letter_job(job, message=message, error_code=error_code)


def _merge_ingest_stats(text_stats: dict[str, Any], visual_stats: dict[str, Any]) -> dict[str, Any]:
    merged = dict(text_stats)
    merged["section_count"] = int(text_stats.get("section_count") or 0) + int(visual_stats.get("visual_ocr_section_count") or 0)
    merged["chunk_count"] = int(text_stats.get("chunk_count") or 0) + int(visual_stats.get("visual_ocr_chunk_count") or 0)
    merged["section_preview"] = list(visual_stats.get("section_preview") or text_stats.get("section_preview") or [])
    merged["visual_asset_count"] = int(visual_stats.get("visual_asset_count") or 0)
    merged["visual_ocr_chunk_count"] = int(visual_stats.get("visual_ocr_chunk_count") or 0)
    merged["visual_provider"] = str(visual_stats.get("visual_provider") or "")
    if visual_stats.get("visual_ms") is not None:
        merged["visual_ms"] = float(visual_stats.get("visual_ms") or 0.0)
    return merged


def _default_suffix_for_mime(mime_type: str) -> str:
    if mime_type == "image/png":
        return ".png"
    if mime_type == "image/jpeg":
        return ".jpg"
    return ".bin"


def _summary(text: str, limit: int) -> str:
    compact = " ".join(part.strip() for part in text.splitlines() if part.strip())
    return compact[:limit].strip()


def _hash_text(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


def _hash_bytes(data: bytes) -> str:
    return hashlib.sha256(data or b"").hexdigest()


def _to_json(data: dict[str, Any] | None) -> str:
    return json.dumps(data or {}, ensure_ascii=False)


if __name__ == "__main__":
    run_forever()
