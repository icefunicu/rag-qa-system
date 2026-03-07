from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Iterable, List, Sequence

import psycopg


@dataclass(frozen=True)
class JobRecord:
    job_id: str
    document_id: str
    status: str
    retry_count: int


@dataclass(frozen=True)
class DocumentRecord:
    id: str
    corpus_id: str
    file_name: str
    file_type: str
    storage_key: str


@dataclass(frozen=True)
class SectionRecord:
    section_id: str
    section_index: int
    section_title: str
    section_summary: str
    normalized_title: str
    normalized_summary: str
    search_terms: Sequence[str] = field(default_factory=tuple)
    page_or_loc: str = ""
    char_start: int = 0
    char_end: int = 0
    chunk_start_index: int = 0
    chunk_end_index: int = 0
    qdrant_point_id: str = ""
    ingest_profile: str = "default"


@dataclass(frozen=True)
class ChunkRecord:
    chunk_index: int
    text: str
    page_or_loc: str
    token_count: int
    qdrant_point_id: str
    section_id: str = ""
    section_title: str = ""
    normalized_text: str = ""
    search_terms: Sequence[str] = field(default_factory=tuple)
    char_count: int = 0
    ingest_profile: str = "default"


class DB:
    def __init__(self, dsn: str):
        self._dsn = dsn

    def connect(self) -> psycopg.Connection:
        return psycopg.connect(self._dsn)

    def load_job_with_document(self, conn: psycopg.Connection, job_id: str) -> tuple[JobRecord, DocumentRecord]:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT j.id, j.document_id, j.status, j.retry_count,
                       d.id, d.corpus_id, d.file_name, d.file_type, d.storage_key
                FROM ingest_jobs j
                JOIN documents d ON d.id = j.document_id
                WHERE j.id = %s
                """,
                (job_id,),
            )
            row = cur.fetchone()
            if row is None:
                raise ValueError(f"job not found: {job_id}")

        job = JobRecord(
            job_id=str(row[0]),
            document_id=str(row[1]),
            status=str(row[2]),
            retry_count=int(row[3]),
        )
        doc = DocumentRecord(
            id=str(row[4]),
            corpus_id=str(row[5]),
            file_name=str(row[6]),
            file_type=str(row[7]),
            storage_key=str(row[8]),
        )
        return job, doc

    def mark_running(self, conn: psycopg.Connection, job_id: str, progress: int) -> None:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE ingest_jobs
                SET status = 'running', progress = %s, error_message = NULL, updated_at = NOW()
                WHERE id = %s
                """,
                (progress, job_id),
            )
            cur.execute(
                """
                UPDATE documents
                SET status = 'indexing'
                WHERE id = (SELECT document_id FROM ingest_jobs WHERE id = %s)
                """,
                (job_id,),
            )

    def update_progress(self, conn: psycopg.Connection, job_id: str, progress: int) -> None:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE ingest_jobs
                SET progress = %s, updated_at = NOW()
                WHERE id = %s
                """,
                (progress, job_id),
            )

    def replace_chunks(
        self,
        conn: psycopg.Connection,
        document_id: str,
        chunks: List[ChunkRecord],
    ) -> None:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM doc_chunks WHERE document_id = %s", (document_id,))
            self._insert_chunks(cur, document_id, chunks)

    def replace_sections(
        self,
        conn: psycopg.Connection,
        document_id: str,
        sections: List[SectionRecord],
    ) -> None:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM doc_sections WHERE document_id = %s", (document_id,))
            self._insert_sections(cur, document_id, sections)

    def replace_document_index(
        self,
        conn: psycopg.Connection,
        document_id: str,
        *,
        sections: List[SectionRecord],
        chunks: List[ChunkRecord],
    ) -> None:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM doc_chunks WHERE document_id = %s", (document_id,))
            cur.execute("DELETE FROM doc_sections WHERE document_id = %s", (document_id,))
            self._insert_sections(cur, document_id, sections)
            self._insert_chunks(cur, document_id, chunks)

    def mark_done(self, conn: psycopg.Connection, job_id: str) -> None:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE ingest_jobs
                SET status = 'done', progress = 100, error_message = NULL, updated_at = NOW()
                WHERE id = %s
                """,
                (job_id,),
            )
            cur.execute(
                """
                UPDATE documents
                SET status = 'ready'
                WHERE id = (SELECT document_id FROM ingest_jobs WHERE id = %s)
                """,
                (job_id,),
            )

    def mark_failed(self, conn: psycopg.Connection, job_id: str, error_message: str) -> None:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE ingest_jobs
                SET status = 'failed', error_message = %s, updated_at = NOW()
                WHERE id = %s
                """,
                (error_message[:3000], job_id),
            )
            cur.execute(
                """
                UPDATE documents
                SET status = 'failed'
                WHERE id = (SELECT document_id FROM ingest_jobs WHERE id = %s)
                """,
                (job_id,),
            )

    def increase_retry(self, conn: psycopg.Connection, job_id: str) -> int:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE ingest_jobs
                SET retry_count = retry_count + 1, updated_at = NOW()
                WHERE id = %s
                RETURNING retry_count
                """,
                (job_id,),
            )
            row = cur.fetchone()
            if row is None:
                raise ValueError(f"job not found for retry: {job_id}")
            return int(row[0])

    def mark_queued_for_retry(self, conn: psycopg.Connection, job_id: str, error_message: str) -> None:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE ingest_jobs
                SET status = 'queued', progress = 0, error_message = %s, updated_at = NOW()
                WHERE id = %s
                """,
                (error_message[:3000], job_id),
            )

    def append_ingest_event(
        self, conn: psycopg.Connection, job_id: str, stage: str, message: str = ""
    ) -> None:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO ingest_events (id, job_id, stage, message, created_at)
                VALUES (%s, %s, %s, %s, NOW())
                """,
                (str(uuid.uuid4()), job_id, stage, message[:2000] if message else ""),
            )

    def mark_dead_letter(
        self,
        conn: psycopg.Connection,
        job_id: str,
        error_message: str,
        error_category: str = "unknown",
    ) -> None:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE ingest_jobs
                SET status = 'dead_letter', error_message = %s,
                    error_category = %s, updated_at = NOW()
                WHERE id = %s
                """,
                (error_message[:3000], error_category, job_id),
            )
            cur.execute(
                """
                UPDATE documents
                SET status = 'failed'
                WHERE id = (SELECT document_id FROM ingest_jobs WHERE id = %s)
                """,
                (job_id,),
            )

    def count_chunks_by_document(self, conn: psycopg.Connection, document_id: str) -> int:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) FROM doc_chunks WHERE document_id = %s",
                (document_id,),
            )
            row = cur.fetchone()
            return int(row[0]) if row else 0

    def count_sections_by_document(self, conn: psycopg.Connection, document_id: str) -> int:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) FROM doc_sections WHERE document_id = %s",
                (document_id,),
            )
            row = cur.fetchone()
            return int(row[0]) if row else 0

    def is_job_cancelled(self, conn: psycopg.Connection, job_id: str) -> bool:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT status FROM ingest_jobs WHERE id = %s",
                (job_id,),
            )
            row = cur.fetchone()
            if row is None:
                return False
            return row[0] == "cancelled"

    def _insert_sections(
        self,
        cur: psycopg.Cursor,
        document_id: str,
        sections: Sequence[SectionRecord],
    ) -> None:
        if not sections:
            return

        rows = [
            (
                section.section_id,
                document_id,
                section.section_index,
                section.section_title,
                section.section_summary,
                section.normalized_title,
                section.normalized_summary,
                list(section.search_terms),
                section.page_or_loc,
                section.char_start,
                section.char_end,
                section.chunk_start_index,
                section.chunk_end_index,
                section.qdrant_point_id,
                section.ingest_profile,
            )
            for section in sections
        ]
        self._execute_batched_insert(
            cur,
            """
            INSERT INTO doc_sections (
                id,
                document_id,
                section_index,
                section_title,
                section_summary,
                normalized_title,
                normalized_summary,
                search_terms,
                page_or_loc,
                char_start,
                char_end,
                chunk_start_index,
                chunk_end_index,
                qdrant_point_id,
                ingest_profile
            ) VALUES
            """,
            rows,
        )

    def _insert_chunks(
        self,
        cur: psycopg.Cursor,
        document_id: str,
        chunks: Sequence[ChunkRecord],
    ) -> None:
        if not chunks:
            return

        rows = [
            (
                str(uuid.uuid4()),
                document_id,
                chunk.chunk_index,
                chunk.text,
                chunk.page_or_loc,
                chunk.token_count,
                chunk.qdrant_point_id,
                chunk.section_id or None,
                chunk.section_title,
                chunk.normalized_text,
                list(chunk.search_terms),
                chunk.char_count,
                chunk.ingest_profile,
            )
            for chunk in chunks
        ]
        self._execute_batched_insert(
            cur,
            """
            INSERT INTO doc_chunks (
                id,
                document_id,
                chunk_index,
                chunk_text,
                page_or_loc,
                token_count,
                qdrant_point_id,
                section_id,
                section_title,
                normalized_text,
                search_terms,
                char_count,
                ingest_profile
            ) VALUES
            """,
            rows,
        )

    def _execute_batched_insert(
        self,
        cur: psycopg.Cursor,
        prefix: str,
        rows: Sequence[Sequence[object]],
        *,
        batch_size: int = 256,
    ) -> None:
        if not rows:
            return

        column_count = len(rows[0])
        single_placeholder = "(" + ", ".join(["%s"] * column_count) + ")"
        for start in range(0, len(rows), batch_size):
            batch = rows[start : start + batch_size]
            placeholders = ", ".join([single_placeholder] * len(batch))
            flat_params = [item for row in batch for item in row]
            cur.execute(prefix + placeholders, flat_params)
