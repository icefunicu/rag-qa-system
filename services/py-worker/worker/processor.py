from __future__ import annotations

import logging
import tempfile
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Sequence

from worker.chunking import (
    Chunk,
    ParsedSegment,
    build_search_terms,
    chunk_segments,
    chunk_segments_by_chars,
)
from worker.config import WorkerConfig
from worker.db import ChunkRecord, DB, SectionRecord
from worker.embedding import EmbeddingClient
from worker.metadata_enhancer import MetadataEnhancer
from worker.parser import parse_document
from worker.qdrant_indexer import IndexPoint, QdrantIndexer
from worker.runtime_progress import NoopRuntimeProgressTracker, RuntimeProgressTracker
from worker.storage import S3Store


ERROR_CATEGORY_DOWNLOAD = "download_error"
ERROR_CATEGORY_PARSE = "parse_error"
ERROR_CATEGORY_EMBED = "embed_error"
ERROR_CATEGORY_INDEX = "index_error"
ERROR_CATEGORY_VERIFY = "verify_error"
ERROR_CATEGORY_UNKNOWN = "unknown"
EMBED_PROGRESS_START = 55
EMBED_PROGRESS_END = 80

logger = logging.getLogger("py-worker")


@dataclass(frozen=True)
class IngestTuning:
    profile: str
    index_mode: str
    chunk_unit: str
    source_text_chars: int
    chunk_size: int
    chunk_overlap: int
    embedding_batch_size: int
    embedding_batch_max_chars: int
    dense_chunk_embeddings_enabled: bool = True
    dense_section_embeddings_enabled: bool = False


@dataclass(frozen=True)
class ChunkingResult:
    chunks: list[Chunk]
    tuning: IngestTuning
    sections: list[ParsedSegment] = field(default_factory=list)


class IngestError(Exception):
    def __init__(self, message: str, category: str = ERROR_CATEGORY_UNKNOWN):
        super().__init__(message)
        self.category = category


class CancelledError(Exception):
    """Raised when the job has been cancelled by the user."""
    pass



class IngestProcessor:
    def __init__(
        self,
        cfg: WorkerConfig,
        *,
        progress_tracker: RuntimeProgressTracker | None = None,
    ):
        self._cfg = cfg
        self._db = DB(cfg.postgres_dsn)
        self._s3 = S3Store(
            endpoint=cfg.s3_endpoint,
            access_key=cfg.s3_access_key,
            secret_key=cfg.s3_secret_key,
            bucket=cfg.s3_bucket,
            use_ssl=cfg.s3_use_ssl,
        )
        self._embedding_client = EmbeddingClient(cfg)
        self._metadata_enhancer = MetadataEnhancer(max_keywords=cfg.metadata_max_keywords)
        self._progress_tracker = progress_tracker or NoopRuntimeProgressTracker()

    def process_job(self, job_id: str) -> tuple[bool, str]:
        try:
            with self._db.connect() as conn:
                conn.autocommit = False
                job, doc = self._db.load_job_with_document(conn, job_id)
                self._db.mark_running(conn, job.job_id, progress=5)
                self._db.append_ingest_event(conn, job.job_id, "queued", "job picked up by worker")
                conn.commit()
                self._set_runtime_progress(
                    job.job_id,
                    status="running",
                    overall_progress=5,
                    stage="queued",
                    message="job picked up by worker",
                )

            with tempfile.TemporaryDirectory(prefix="ragp-ingest-") as tmp_dir:
                file_path = self._stage_download(job.job_id, doc, tmp_dir)
                segments = self._stage_parse(job.job_id, file_path, doc.file_type)
                chunking_result = self._stage_chunk(job.job_id, segments)
                vector_points, db_sections, db_chunks = self._stage_embed(job.job_id, doc, chunking_result)
                embedding_dim = len(vector_points[0].vector) if vector_points else self._cfg.embedding_dim

                self._stage_index(
                    job.job_id,
                    doc,
                    vector_points,
                    db_sections,
                    db_chunks,
                    embedding_dim,
                    chunking_result.tuning.index_mode,
                )
                self._stage_verify(
                    job.job_id,
                    doc,
                    expected_point_count=len(vector_points),
                    expected_section_count=len(db_sections),
                    expected_chunk_count=len(db_chunks),
                    embedding_dim=embedding_dim,
                    index_mode=chunking_result.tuning.index_mode,
                )

                with self._db.connect() as conn:
                    conn.autocommit = False
                    self._db.mark_done(conn, job.job_id)
                    self._db.append_ingest_event(conn, job.job_id, "done", "ingest completed successfully")
                    conn.commit()
                    self._set_runtime_progress(
                        job.job_id,
                        status="done",
                        overall_progress=100,
                        stage="done",
                        message="ingest completed successfully",
                        details={
                            "document_id": doc.id,
                            "embedding_dim": embedding_dim,
                            "vector_count": len(vector_points),
                            "section_count": len(db_sections),
                            "chunk_count": len(db_chunks),
                        },
                    )

            return True, "indexed"
        except CancelledError:
            self._set_runtime_progress(
                job_id,
                status="cancelled",
                overall_progress=0,
                stage="cancelled",
                message="job cancelled by user",
            )
            logger.info("job processing stopped (cancelled)", extra={"job_id": job_id})
            return False, "cancelled"
        except IngestError as exc:
            return self._handle_failure(job_id, str(exc), exc.category)
        except Exception as exc:  # noqa: BLE001
            return self._handle_failure(job_id, str(exc), ERROR_CATEGORY_UNKNOWN)

    def _check_cancelled(self, job_id: str) -> None:
        """检查作业是否已被取消，若是则抛出异常"""
        with self._db.connect() as conn:
            cancelled = self._db.is_job_cancelled(conn, job_id)
            if cancelled is True:
                raise CancelledError(f"Job {job_id} was cancelled")

    def _get_embedding_progress(self, processed_chunks: int, total_chunks: int) -> int:
        if total_chunks <= 0:
            return EMBED_PROGRESS_END

        if processed_chunks <= 0:
            return EMBED_PROGRESS_START

        if processed_chunks >= total_chunks:
            return EMBED_PROGRESS_END

        bounded_processed = min(max(processed_chunks, 0), total_chunks)
        span = max(EMBED_PROGRESS_END - EMBED_PROGRESS_START - 1, 1)
        denominator = max(total_chunks - 1, 1)
        return EMBED_PROGRESS_START + 1 + int(((bounded_processed - 1) / denominator) * span)

    def _set_runtime_progress(
        self,
        job_id: str,
        *,
        status: str,
        overall_progress: int,
        stage: str,
        message: str = "",
        details: dict[str, Any] | None = None,
    ) -> None:
        self._progress_tracker.set(
            job_id,
            status=status,
            overall_progress=overall_progress,
            stage=stage,
            message=message,
            details=details,
        )

    def _build_embedding_details(
        self,
        *,
        tuning: IngestTuning,
        processed_chunks: int,
        total_chunks: int,
        processed_batches: int,
        total_batches: int,
        current_batch: int | None = None,
        current_batch_size: int | None = None,
        dense_chunk_count: int = 0,
        dense_section_count: int = 0,
    ) -> dict[str, Any]:
        details: dict[str, Any] = {
            "processed_chunks": processed_chunks,
            "total_chunks": total_chunks,
            "processed_batches": processed_batches,
            "total_batches": total_batches,
            "index_mode": tuning.index_mode,
            "chunk_unit": tuning.chunk_unit,
            "batch_size": tuning.embedding_batch_size,
            "batch_max_chars": tuning.embedding_batch_max_chars,
            "chunk_size": tuning.chunk_size,
            "chunk_overlap": tuning.chunk_overlap,
            "source_text_chars": tuning.source_text_chars,
            "ingest_profile": tuning.profile,
            "provider": self._cfg.embedding_provider,
            "model": self._cfg.embedding_model,
            "dense_chunk_embeddings_enabled": tuning.dense_chunk_embeddings_enabled,
            "dense_section_embeddings_enabled": tuning.dense_section_embeddings_enabled,
            "dense_chunk_count": dense_chunk_count,
            "dense_section_count": dense_section_count,
        }
        if total_chunks > 0:
            details["stage_progress_percent"] = int((processed_chunks / total_chunks) * 100)
        if current_batch is not None:
            details["current_batch"] = current_batch
        if current_batch_size is not None:
            details["current_batch_size"] = current_batch_size
        return details

    def _select_ingest_tuning(self, source_text_chars: int) -> IngestTuning:
        if (
            self._cfg.long_text_sparse_only_enabled
            and source_text_chars >= self._cfg.long_text_sparse_only_threshold_chars
        ):
            return IngestTuning(
                profile="sparse_only",
                index_mode="sparse_only",
                chunk_unit="chars",
                source_text_chars=source_text_chars,
                chunk_size=self._cfg.long_text_sparse_chunk_chars,
                chunk_overlap=self._cfg.long_text_sparse_chunk_overlap_chars,
                embedding_batch_size=0,
                embedding_batch_max_chars=0,
                dense_chunk_embeddings_enabled=False,
                dense_section_embeddings_enabled=False,
            )

        if source_text_chars >= self._cfg.section_summary_threshold_chars:
            return IngestTuning(
                profile="section_dense_sparse",
                index_mode="section_dense_sparse",
                chunk_unit="chars",
                source_text_chars=source_text_chars,
                chunk_size=self._cfg.long_text_sparse_chunk_chars,
                chunk_overlap=self._cfg.long_text_sparse_chunk_overlap_chars,
                embedding_batch_size=self._cfg.long_text_embedding_batch_size,
                embedding_batch_max_chars=self._cfg.long_text_embedding_batch_max_chars,
                dense_chunk_embeddings_enabled=False,
                dense_section_embeddings_enabled=True,
            )

        if self._cfg.long_text_mode_enabled and source_text_chars >= self._cfg.long_text_threshold_chars:
            return IngestTuning(
                profile="long_text_dense",
                index_mode="dense",
                chunk_unit="tokens",
                source_text_chars=source_text_chars,
                chunk_size=self._cfg.long_text_chunk_size,
                chunk_overlap=self._cfg.long_text_chunk_overlap,
                embedding_batch_size=self._cfg.long_text_embedding_batch_size,
                embedding_batch_max_chars=self._cfg.long_text_embedding_batch_max_chars,
                dense_chunk_embeddings_enabled=True,
                dense_section_embeddings_enabled=False,
            )

        return IngestTuning(
            profile="default",
            index_mode="dense",
            chunk_unit="tokens",
            source_text_chars=source_text_chars,
            chunk_size=self._cfg.default_chunk_size,
            chunk_overlap=self._cfg.default_chunk_overlap,
            embedding_batch_size=self._cfg.embedding_batch_size,
            embedding_batch_max_chars=self._cfg.embedding_batch_max_chars,
            dense_chunk_embeddings_enabled=True,
            dense_section_embeddings_enabled=False,
        )

    def _stage_download(self, job_id: str, doc, tmp_dir: str) -> Path:
        self._check_cancelled(job_id)
        try:
            self._set_runtime_progress(
                job_id,
                status="running",
                overall_progress=5,
                stage="downloading",
                message=f"downloading {doc.storage_key}",
                details={"file_type": doc.file_type, "storage_key": doc.storage_key},
            )
            with self._db.connect() as conn:
                conn.autocommit = False
                self._db.append_ingest_event(conn, job_id, "downloading", f"downloading {doc.storage_key}")
                conn.commit()

            file_path = Path(tmp_dir) / f"source.{doc.file_type}"
            self._s3.download_to(doc.storage_key, file_path)

            with self._db.connect() as conn:
                conn.autocommit = False
                self._db.update_progress(conn, job_id, progress=20)
                conn.commit()
                self._set_runtime_progress(
                    job_id,
                    status="running",
                    overall_progress=20,
                    stage="downloading",
                    message="source file downloaded",
                    details={"file_type": doc.file_type},
                )

            return file_path
        except IngestError:
            raise
        except Exception as exc:
            raise IngestError(f"download failed: {exc}", ERROR_CATEGORY_DOWNLOAD) from exc

    def _stage_parse(self, job_id: str, file_path: Path, file_type: str):
        self._check_cancelled(job_id)
        try:
            self._set_runtime_progress(
                job_id,
                status="running",
                overall_progress=20,
                stage="parsing",
                message=f"parsing {file_type} document",
                details={"file_type": file_type},
            )
            with self._db.connect() as conn:
                conn.autocommit = False
                self._db.append_ingest_event(conn, job_id, "parsing", f"parsing {file_type} document")
                conn.commit()

            segments = parse_document(file_path, file_type)
            self._set_runtime_progress(
                job_id,
                status="running",
                overall_progress=30,
                stage="parsing",
                message="document parsed",
                details={"file_type": file_type, "segment_count": len(segments)},
            )

            if self._cfg.metadata_enhancement_enabled:
                self._metadata_enhancer.enhance_segments(
                    segments,
                    max_chars=self._cfg.metadata_sampling_max_chars,
                )

            return segments
        except IngestError:
            raise
        except Exception as exc:
            raise IngestError(f"parse failed: {exc}", ERROR_CATEGORY_PARSE) from exc

    def _stage_chunk(self, job_id: str, segments: Sequence[ParsedSegment]) -> ChunkingResult:
        self._check_cancelled(job_id)
        try:
            source_text_chars = sum(len(seg.text.strip()) for seg in segments if seg.text.strip())
            tuning = self._select_ingest_tuning(source_text_chars)
            self._set_runtime_progress(
                job_id,
                status="running",
                overall_progress=30,
                stage="chunking",
                message="splitting into chunks",
                details={
                    "segment_count": len(segments),
                    "source_text_chars": source_text_chars,
                    "ingest_profile": tuning.profile,
                    "index_mode": tuning.index_mode,
                    "chunk_unit": tuning.chunk_unit,
                    "chunk_size": tuning.chunk_size,
                    "chunk_overlap": tuning.chunk_overlap,
                },
            )
            with self._db.connect() as conn:
                conn.autocommit = False
                self._db.append_ingest_event(conn, job_id, "chunking", "splitting into chunks")
                conn.commit()

            if tuning.chunk_unit == "chars":
                chunks = chunk_segments_by_chars(
                    segments,
                    chunk_chars=tuning.chunk_size,
                    overlap_chars=tuning.chunk_overlap,
                )
            else:
                chunks = chunk_segments(
                    segments,
                    chunk_tokens=tuning.chunk_size,
                    overlap_tokens=tuning.chunk_overlap,
                )
            chunks = self._trim_chunk_search_terms(chunks)
            if not chunks:
                raise ValueError("document parse succeeded but no text chunks generated")

            with self._db.connect() as conn:
                conn.autocommit = False
                self._db.update_progress(conn, job_id, progress=40)
                conn.commit()
                self._set_runtime_progress(
                    job_id,
                    status="running",
                    overall_progress=40,
                    stage="chunking",
                    message="chunks generated",
                    details={
                        "total_chunks": len(chunks),
                        "source_text_chars": source_text_chars,
                        "ingest_profile": tuning.profile,
                        "index_mode": tuning.index_mode,
                        "chunk_unit": tuning.chunk_unit,
                        "chunk_size": tuning.chunk_size,
                        "chunk_overlap": tuning.chunk_overlap,
                    },
                )

            return ChunkingResult(chunks=chunks, tuning=tuning, sections=list(segments))
        except IngestError:
            raise
        except Exception as exc:
            raise IngestError(f"chunking failed: {exc}", ERROR_CATEGORY_PARSE) from exc

    def _stage_embed(
        self,
        job_id: str,
        doc,
        chunking_result: ChunkingResult,
    ) -> tuple[list[IndexPoint], list[SectionRecord], list[ChunkRecord]]:
        self._check_cancelled(job_id)
        try:
            chunks = chunking_result.chunks
            tuning = chunking_result.tuning
            sections = self._build_section_records(doc.id, chunking_result.sections, chunks, tuning.profile)
            dense_chunk_count = len(chunks) if tuning.dense_chunk_embeddings_enabled else 0
            dense_section_count = len(sections) if tuning.dense_section_embeddings_enabled else 0
            total_dense_inputs = dense_chunk_count + dense_section_count

            if total_dense_inputs == 0:
                db_chunks = self._build_chunk_records(doc.id, chunks, tuning.profile)
                with self._db.connect() as conn:
                    conn.autocommit = False
                    self._db.append_ingest_event(conn, job_id, "embedding", "no dense embedding required")
                    self._db.update_progress(conn, job_id, progress=EMBED_PROGRESS_END)
                    conn.commit()
                self._set_runtime_progress(
                    job_id,
                    status="running",
                    overall_progress=EMBED_PROGRESS_END,
                    stage="embedding",
                    message="no dense embedding required",
                    details=self._build_embedding_details(
                        tuning=tuning,
                        processed_chunks=0,
                        total_chunks=0,
                        processed_batches=0,
                        total_batches=0,
                        dense_chunk_count=dense_chunk_count,
                        dense_section_count=dense_section_count,
                    ),
                )
                return [], sections, db_chunks

            embedding_items: list[tuple[str, Any]] = []
            if tuning.dense_chunk_embeddings_enabled:
                embedding_items.extend(("chunk", chunk) for chunk in chunks)
            if tuning.dense_section_embeddings_enabled:
                embedding_items.extend(("section", section) for section in sections)

            batches = list(
                self._iter_embedding_batches(
                    embedding_items,
                    batch_size=tuning.embedding_batch_size,
                    batch_max_chars=tuning.embedding_batch_max_chars,
                )
            )
            total_batches = len(batches)
            self._set_runtime_progress(
                job_id,
                status="running",
                overall_progress=EMBED_PROGRESS_START,
                stage="embedding",
                message=f"embedding {total_dense_inputs} items",
                details=self._build_embedding_details(
                    tuning=tuning,
                    processed_chunks=0,
                    total_chunks=total_dense_inputs,
                    processed_batches=0,
                    total_batches=total_batches,
                    dense_chunk_count=dense_chunk_count,
                    dense_section_count=dense_section_count,
                ),
            )
            with self._db.connect() as conn:
                conn.autocommit = False
                self._db.append_ingest_event(
                    conn,
                    job_id,
                    "embedding",
                    f"embedding {total_dense_inputs} items (chunks={dense_chunk_count}, sections={dense_section_count})",
                )
                self._db.update_progress(conn, job_id, progress=EMBED_PROGRESS_START)
                conn.commit()

            vector_points: list[IndexPoint] = []
            chunk_point_ids: dict[int, str] = {}
            section_point_ids: dict[str, str] = {}
            processed_count = 0
            last_progress = EMBED_PROGRESS_START

            for batch_index, batch in enumerate(batches, start=1):
                self._check_cancelled(job_id)
                texts = [self._embedding_text(item) for item in batch]
                vectors = self._embedding_client.embed_batch(texts)
                if len(vectors) != len(batch):
                    raise RuntimeError("embedding batch result count mismatch")

                for (kind, item), vector in zip(batch, vectors):
                    point_id = str(uuid.uuid4())
                    if kind == "chunk":
                        chunk = item
                        chunk_point_ids[chunk.chunk_index] = point_id
                        payload = {
                            "document_id": doc.id,
                            "corpus_id": doc.corpus_id,
                            "file_name": doc.file_name,
                            "file_type": doc.file_type,
                            "page_or_loc": chunk.page_or_loc,
                            "chunk_index": chunk.chunk_index,
                            "text": chunk.text,
                            "point_type": "chunk",
                            "section_index": chunk.section_index,
                            "section_title": chunk.section_title,
                            "section_id": self._section_id(doc.id, chunk.section_index),
                        }
                    else:
                        section = item
                        section_point_ids[section.section_id] = point_id
                        payload = {
                            "document_id": doc.id,
                            "corpus_id": doc.corpus_id,
                            "file_name": doc.file_name,
                            "file_type": doc.file_type,
                            "page_or_loc": section.page_or_loc,
                            "text": section.section_summary,
                            "point_type": "section_summary",
                            "section_id": section.section_id,
                            "section_index": section.section_index,
                            "section_title": section.section_title,
                        }
                    vector_points.append(IndexPoint(point_id=point_id, vector=vector, payload=payload))

                processed_count += len(batch)
                next_progress = self._get_embedding_progress(processed_count, total_dense_inputs)
                if next_progress > last_progress:
                    with self._db.connect() as conn:
                        conn.autocommit = False
                        self._db.update_progress(conn, job_id, progress=next_progress)
                        conn.commit()
                    last_progress = next_progress

                self._set_runtime_progress(
                    job_id,
                    status="running",
                    overall_progress=last_progress,
                    stage="embedding",
                    message=f"embedded {processed_count}/{total_dense_inputs} items ({batch_index}/{total_batches} batches)",
                    details=self._build_embedding_details(
                        tuning=tuning,
                        processed_chunks=processed_count,
                        total_chunks=total_dense_inputs,
                        processed_batches=batch_index,
                        total_batches=total_batches,
                        current_batch=batch_index,
                        current_batch_size=len(batch),
                        dense_chunk_count=dense_chunk_count,
                        dense_section_count=dense_section_count,
                    ),
                )

            db_sections = self._attach_section_point_ids(sections, section_point_ids)
            db_chunks = self._build_chunk_records(doc.id, chunks, tuning.profile, chunk_point_ids)
            return vector_points, db_sections, db_chunks
        except IngestError:
            raise
        except Exception as exc:
            raise IngestError(f"embedding failed: {exc}", ERROR_CATEGORY_EMBED) from exc

    def _iter_embedding_batches(self, chunks, *, batch_size: int, batch_max_chars: int):
        batch = []
        current_chars = 0

        for chunk in chunks:
            chunk_chars = len(self._embedding_text(chunk))
            reaches_batch_limit = len(batch) >= batch_size
            reaches_char_limit = batch and (current_chars + chunk_chars > batch_max_chars)
            if reaches_batch_limit or reaches_char_limit:
                yield batch
                batch = []
                current_chars = 0

            batch.append(chunk)
            current_chars += chunk_chars

        if batch:
            yield batch

    def _embedding_text(self, item: Any) -> str:
        if isinstance(item, tuple) and len(item) == 2:
            return self._embedding_text(item[1])
        if hasattr(item, "text"):
            return str(getattr(item, "text") or "")
        if hasattr(item, "section_summary"):
            return str(getattr(item, "section_summary") or "")
        raise ValueError("embedding item does not expose text")

    def _section_id(self, document_id: str, section_index: int) -> str:
        return f"{document_id}:section:{max(section_index, 1)}"

    def _build_section_records(
        self,
        document_id: str,
        sections: Sequence[ParsedSegment],
        chunks: Sequence[Chunk],
        ingest_profile: str,
    ) -> list[SectionRecord]:
        grouped_chunks: dict[int, list[Chunk]] = {}
        for chunk in chunks:
            grouped_chunks.setdefault(chunk.section_index or 1, []).append(chunk)

        effective_sections = list(sections)
        if not effective_sections and chunks:
            joined = "\n\n".join(chunk.text for chunk in chunks)
            effective_sections = [
                ParsedSegment(
                    text=joined,
                    page_or_loc=chunks[0].page_or_loc,
                    section_index=1,
                    section_title="section 1",
                    char_start=0,
                    char_end=len(joined),
                    kind="section",
                )
            ]

        records: list[SectionRecord] = []
        for ordinal, segment in enumerate(effective_sections, start=1):
            section_index = segment.section_index or ordinal
            section_id = self._section_id(document_id, section_index)
            section_chunks = sorted(grouped_chunks.get(section_index, []), key=lambda item: item.chunk_index)
            summary = self._build_section_summary(segment, section_chunks)
            records.append(
                SectionRecord(
                    section_id=section_id,
                    section_index=section_index,
                    section_title=segment.section_title or f"section {section_index}",
                    section_summary=summary,
                    normalized_title=(segment.section_title or "").strip().lower(),
                    normalized_summary=summary.strip().lower(),
                    search_terms=self._trim_search_terms(
                        build_search_terms(
                            summary,
                            title=segment.section_title,
                            max_terms=self._cfg.search_terms_max_per_chunk,
                        )
                    ),
                    page_or_loc=segment.page_or_loc,
                    char_start=segment.char_start,
                    char_end=segment.char_end,
                    chunk_start_index=section_chunks[0].chunk_index if section_chunks else 0,
                    chunk_end_index=section_chunks[-1].chunk_index if section_chunks else 0,
                    ingest_profile=ingest_profile,
                )
            )
        return records

    def _attach_section_point_ids(
        self,
        sections: Sequence[SectionRecord],
        point_ids: dict[str, str],
    ) -> list[SectionRecord]:
        return [
            SectionRecord(
                section_id=section.section_id,
                section_index=section.section_index,
                section_title=section.section_title,
                section_summary=section.section_summary,
                normalized_title=section.normalized_title,
                normalized_summary=section.normalized_summary,
                search_terms=section.search_terms,
                page_or_loc=section.page_or_loc,
                char_start=section.char_start,
                char_end=section.char_end,
                chunk_start_index=section.chunk_start_index,
                chunk_end_index=section.chunk_end_index,
                qdrant_point_id=point_ids.get(section.section_id, ""),
                ingest_profile=section.ingest_profile,
            )
            for section in sections
        ]

    def _build_chunk_records(
        self,
        document_id: str,
        chunks: Sequence[Chunk],
        ingest_profile: str,
        point_ids: dict[int, str] | None = None,
    ) -> list[ChunkRecord]:
        effective_point_ids = point_ids or {}
        return [
            ChunkRecord(
                chunk_index=chunk.chunk_index,
                text=chunk.text,
                page_or_loc=chunk.page_or_loc,
                token_count=chunk.token_count,
                qdrant_point_id=effective_point_ids.get(chunk.chunk_index, f"sparse:{document_id}:{chunk.chunk_index}"),
                section_id=self._section_id(document_id, chunk.section_index or 1),
                section_title=chunk.section_title,
                normalized_text=chunk.normalized_text,
                search_terms=self._trim_search_terms(chunk.search_terms),
                char_count=chunk.char_count or len(chunk.text),
                ingest_profile=ingest_profile,
            )
            for chunk in chunks
        ]

    def _trim_chunk_search_terms(self, chunks: Sequence[Chunk]) -> list[Chunk]:
        trimmed: list[Chunk] = []
        for chunk in chunks:
            trimmed.append(
                Chunk(
                    chunk_index=chunk.chunk_index,
                    text=chunk.text,
                    page_or_loc=chunk.page_or_loc,
                    token_count=chunk.token_count,
                    section_index=chunk.section_index,
                    section_title=chunk.section_title,
                    normalized_text=chunk.normalized_text,
                    search_terms=self._trim_search_terms(chunk.search_terms),
                    char_count=chunk.char_count,
                )
            )
        return trimmed

    def _trim_search_terms(self, terms: Sequence[str]) -> tuple[str, ...]:
        return tuple(terms[: self._cfg.search_terms_max_per_chunk])

    def _build_section_summary(self, segment: ParsedSegment, chunks: Sequence[Chunk]) -> str:
        parts: list[str] = []
        if segment.section_title:
            parts.append(segment.section_title.strip())
        if chunks:
            parts.extend(chunk.text.strip() for chunk in chunks[:2] if chunk.text.strip())
        elif segment.text.strip():
            parts.append(segment.text.strip())
        summary = "\n".join(part for part in parts if part).strip()
        return summary[: self._cfg.section_summary_chars]

    def _stage_index(
        self,
        job_id: str,
        doc,
        vector_points: list[IndexPoint],
        db_sections: list[SectionRecord],
        db_chunks: list[ChunkRecord],
        embedding_dim: int,
        index_mode: str,
    ) -> None:
        self._check_cancelled(job_id)
        try:
            details = {
                "vector_count": len(vector_points),
                "section_count": len(db_sections),
                "chunk_count": len(db_chunks),
                "embedding_dim": embedding_dim,
                "index_mode": index_mode,
            }

            self._set_runtime_progress(
                job_id,
                status="running",
                overall_progress=EMBED_PROGRESS_END,
                stage="indexing",
                message=f"writing {len(vector_points)} vectors and document structure",
                details=details,
            )
            with self._db.connect() as conn:
                conn.autocommit = False
                self._db.append_ingest_event(
                    conn,
                    job_id,
                    "indexing",
                    f"writing {len(vector_points)} vectors and persisting {len(db_sections)} sections / {len(db_chunks)} chunks",
                )
                conn.commit()

            if vector_points:
                indexer = QdrantIndexer(
                    url=self._cfg.qdrant_url,
                    collection=self._cfg.qdrant_collection,
                    embedding_dim=embedding_dim,
                )
                indexer.replace_document_points(document_id=doc.id, points=vector_points)
            else:
                QdrantIndexer.delete_document_points_if_exists(
                    url=self._cfg.qdrant_url,
                    collection=self._cfg.qdrant_collection,
                    document_id=doc.id,
                )

            with self._db.connect() as conn:
                conn.autocommit = False
                self._db.update_progress(conn, job_id, progress=85)
                self._db.replace_document_index(conn, doc.id, sections=db_sections, chunks=db_chunks)
                conn.commit()
                self._set_runtime_progress(
                    job_id,
                    status="running",
                    overall_progress=85,
                    stage="indexing",
                    message="vectors indexed and document structure persisted",
                    details=details,
                )
        except IngestError:
            raise
        except Exception as exc:
            raise IngestError(f"indexing failed: {exc}", ERROR_CATEGORY_INDEX) from exc

    def _stage_verify(
        self,
        job_id: str,
        doc,
        expected_point_count: int,
        expected_section_count: int,
        expected_chunk_count: int,
        embedding_dim: int,
        index_mode: str,
    ) -> None:
        self._check_cancelled(job_id)
        try:
            self._set_runtime_progress(
                job_id,
                status="running",
                overall_progress=85,
                stage="verifying",
                message="verifying index consistency",
                details={
                    "expected_point_count": expected_point_count,
                    "expected_section_count": expected_section_count,
                    "expected_chunk_count": expected_chunk_count,
                    "embedding_dim": embedding_dim,
                    "index_mode": index_mode,
                },
            )
            with self._db.connect() as conn:
                conn.autocommit = False
                self._db.append_ingest_event(conn, job_id, "verifying", "verifying index consistency")
                conn.commit()

            qdrant_count = QdrantIndexer.count_document_points_if_exists(
                url=self._cfg.qdrant_url,
                collection=self._cfg.qdrant_collection,
                document_id=doc.id,
            )

            with self._db.connect() as conn:
                conn.autocommit = False
                db_section_count = self._db.count_sections_by_document(conn, doc.id)
                db_count = self._db.count_chunks_by_document(conn, doc.id)
                conn.commit()

            if qdrant_count != expected_point_count:
                raise ValueError(
                    f"Qdrant point count mismatch: expected={expected_point_count}, actual={qdrant_count}"
                )
            if db_section_count != expected_section_count:
                raise ValueError(
                    f"DB section count mismatch: expected={expected_section_count}, actual={db_section_count}"
                )
            if db_count != expected_chunk_count:
                raise ValueError(
                    f"DB chunk count mismatch: expected={expected_chunk_count}, actual={db_count}"
                )

            with self._db.connect() as conn:
                conn.autocommit = False
                self._db.update_progress(conn, job_id, progress=95)
                conn.commit()
                self._set_runtime_progress(
                    job_id,
                    status="running",
                    overall_progress=95,
                    stage="verifying",
                    message="index consistency verified",
                    details={
                        "expected_point_count": expected_point_count,
                        "expected_section_count": expected_section_count,
                        "expected_chunk_count": expected_chunk_count,
                        "qdrant_point_count": qdrant_count,
                        "db_section_count": db_section_count,
                        "db_chunk_count": db_count,
                        "index_mode": index_mode,
                    },
                )
        except IngestError:
            raise
        except Exception as exc:
            raise IngestError(f"verification failed: {exc}", ERROR_CATEGORY_VERIFY) from exc

    def _handle_failure(self, job_id: str, error_msg: str, category: str) -> tuple[bool, str]:
        try:
            with self._db.connect() as conn:
                conn.autocommit = False
                retry_count = self._db.increase_retry(conn, job_id)

                if retry_count <= self._cfg.worker_max_retries:
                    self._db.mark_queued_for_retry(
                        conn, job_id, f"[{category}] retrying after error: {error_msg}"
                    )
                    self._db.append_ingest_event(
                        conn,
                        job_id,
                        "failed",
                        f"[{category}] attempt {retry_count}/{self._cfg.worker_max_retries}: {error_msg[:500]}",
                    )
                    conn.commit()
                    logger.warning(
                        "Ingest job scheduled for retry",
                        extra={
                            "job_id": job_id,
                            "status": "retry",
                            "extra_fields": {
                                "error_category": category,
                                "error_message": error_msg[:1000],
                                "retry_count": retry_count,
                                "max_retries": self._cfg.worker_max_retries,
                            },
                        },
                    )
                    self._set_runtime_progress(
                        job_id,
                        status="queued",
                        overall_progress=0,
                        stage="queued",
                        message=f"[{category}] retrying after error: {error_msg[:500]}",
                        details={
                            "error_category": category,
                            "retry_count": retry_count,
                            "max_retries": self._cfg.worker_max_retries,
                        },
                    )
                    return False, "retry"

                self._db.mark_dead_letter(
                    conn,
                    job_id,
                    f"[{category}] ingest failed permanently after {retry_count} retries: {error_msg}",
                    error_category=category,
                )
                self._db.append_ingest_event(
                    conn,
                    job_id,
                    "dead_letter",
                    f"[{category}] moved to dead letter: {error_msg[:500]}",
                )
                conn.commit()
                self._set_runtime_progress(
                    job_id,
                    status="dead_letter",
                    overall_progress=0,
                    stage="dead_letter",
                    message=f"[{category}] moved to dead letter: {error_msg[:500]}",
                    details={"error_category": category, "retry_count": retry_count},
                )

            logger.error(
                "Ingest job moved to dead letter",
                extra={
                    "job_id": job_id,
                    "status": "dead_letter",
                    "extra_fields": {
                        "error_category": category,
                        "error_message": error_msg[:1000],
                        "retry_count": retry_count,
                        "max_retries": self._cfg.worker_max_retries,
                    },
                },
            )
            return False, "dead_letter"
        except Exception:  # noqa: BLE001
            try:
                with self._db.connect() as conn:
                    conn.autocommit = False
                    self._db.mark_failed(conn, job_id, f"catastrophic: {error_msg[:1000]}")
                    conn.commit()
            except Exception:  # noqa: BLE001
                pass

            logger.error(
                "Ingest job failed catastrophically",
                extra={
                    "job_id": job_id,
                    "status": "failed",
                    "extra_fields": {
                        "error_category": category,
                        "error_message": error_msg[:1000],
                    },
                },
            )
            return False, "failed"
