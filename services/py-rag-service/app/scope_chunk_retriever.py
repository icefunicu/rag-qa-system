from __future__ import annotations

import re
from collections import OrderedDict
from contextlib import contextmanager
from dataclasses import dataclass
from queue import Empty, LifoQueue
from threading import Lock
from time import time
from typing import Any, List, Sequence
from uuid import UUID

import psycopg

from .hybrid_retriever import RetrievalResult
from .jieba_compat import load_jieba


ALNUM_TOKEN_RE = re.compile(r"[a-z0-9_]{2,}", re.IGNORECASE)
CJK_BLOCK_RE = re.compile(r"[\u4e00-\u9fff]{2,}")
WHITESPACE_RE = re.compile(r"\s+")


@dataclass(frozen=True)
class CachedSearchResult:
    built_at: float
    payload: list[Any]


@dataclass(frozen=True)
class SectionCandidate:
    section_id: str
    document_id: str
    corpus_id: str
    file_name: str
    page_or_loc: str
    section_title: str
    summary_text: str
    score: float


class ScopeChunkRetriever:
    def __init__(self, postgres_dsn: str, *, ttl_seconds: int = 600, max_scopes: int = 16):
        self._postgres_dsn = postgres_dsn
        self._ttl_seconds = max(ttl_seconds, 1)
        self._max_entries = max(max_scopes, 1)
        self._cache: OrderedDict[str, CachedSearchResult] = OrderedDict()
        self._jieba = load_jieba()
        self._pool = LifoQueue(maxsize=4)
        self._pool_size = 0
        self._pool_lock = Lock()
        self._warm_resources()

    def search(
        self,
        question: str,
        scope: Any,
        top_k: int = 24,
        section_ids: Sequence[str] | None = None,
    ) -> List[RetrievalResult]:
        normalized_question = self._normalize(question)
        if not normalized_question:
            return []

        bounded_top_k = max(top_k, 1)
        section_ids = tuple(sorted(set(section_ids or ())))
        cache_key = self._cache_key("chunks", normalized_question, scope, bounded_top_k, section_ids)
        cached = self._cached_payload(cache_key, bounded_top_k)
        if cached is not None:
            return cached

        query_terms = self._build_query_terms(normalized_question)
        if not query_terms:
            return []

        results = self._search_chunks(
            scope,
            exact_question=normalized_question,
            query_terms=query_terms,
            top_k=bounded_top_k,
            section_ids=section_ids,
        )
        self._store_payload(cache_key, results)
        return results

    def search_sections(self, question: str, scope: Any, top_k: int = 12) -> List[SectionCandidate]:
        normalized_question = self._normalize(question)
        if not normalized_question:
            return []

        bounded_top_k = max(top_k, 1)
        cache_key = self._cache_key("sections", normalized_question, scope, bounded_top_k, ())
        cached = self._cached_payload(cache_key, bounded_top_k)
        if cached is not None:
            return cached

        query_terms = self._build_query_terms(normalized_question)
        if not query_terms:
            return []

        results = self._search_sections(scope, normalized_question, query_terms, bounded_top_k)
        self._store_payload(cache_key, results)
        return results

    def expand_sections(self, scope: Any, section_ids: Sequence[str], top_k: int = 24) -> List[RetrievalResult]:
        unique_section_ids = tuple(sorted(set(section_ids)))
        if not unique_section_ids:
            return []

        corpus_ids = [UUID(item) for item in scope.corpus_ids]
        document_ids = [UUID(item) for item in scope.document_ids]
        query = """
            SELECT
                c.id::text AS chunk_id,
                c.document_id::text AS document_id,
                d.corpus_id::text AS corpus_id,
                d.file_name,
                c.page_or_loc,
                c.chunk_text,
                c.section_id,
                c.section_title
            FROM doc_chunks c
            JOIN documents d ON d.id = c.document_id
            WHERE d.status = 'ready'
              AND d.corpus_id = ANY(%s::uuid[])
              AND c.section_id = ANY(%s::text[])
        """
        params: list[Any] = [corpus_ids, list(unique_section_ids)]
        if document_ids:
            query += " AND d.id = ANY(%s::uuid[])"
            params.append(document_ids)
        query += """
            ORDER BY c.section_id, c.chunk_index
            LIMIT %s
        """
        params.append(max(top_k, 1))

        with self._connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, params)
                rows = cur.fetchall()

        return [
            RetrievalResult(
                chunk_id=str(row[0]),
                document_id=str(row[1]),
                corpus_id=str(row[2]),
                file_name=str(row[3]),
                page_or_loc=str(row[4]),
                text=str(row[5]),
                score=0.0,
                retrieval_type="section_expand",
                section_id=str(row[6] or ""),
                section_title=str(row[7] or ""),
                point_type="chunk",
            )
            for row in rows
        ]

    def scope_revision(self, scope: Any) -> str:
        corpus_ids = [UUID(item) for item in scope.corpus_ids]
        document_ids = [UUID(item) for item in scope.document_ids]
        query = """
            WITH scoped_documents AS (
                SELECT d.id, d.updated_at
                FROM documents d
                WHERE d.status = 'ready'
                  AND d.corpus_id = ANY(%s::uuid[])
        """
        params: list[Any] = [corpus_ids]
        if document_ids:
            query += " AND d.id = ANY(%s::uuid[])"
            params.append(document_ids)
        query += """
            )
            SELECT COALESCE(
                md5(
                    string_agg(
                        sd.id::text || ':' ||
                        COALESCE(dv.max_version::text, '0') || ':' ||
                        COALESCE(sd.updated_at::text, ''),
                        ',' ORDER BY sd.id
                    )
                ),
                'scope:empty'
            )
            FROM scoped_documents sd
            LEFT JOIN (
                SELECT document_id, MAX(version) AS max_version
                FROM document_versions
                GROUP BY document_id
            ) dv ON dv.document_id = sd.id
        """
        try:
            with self._connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(query, params)
                    row = cur.fetchone()
        except Exception:
            return "scope:unknown"
        if row is None or not row[0]:
            return "scope:empty"
        return str(row[0])

    def close(self) -> None:
        while True:
            try:
                conn = self._pool.get_nowait()
            except Empty:
                break
            try:
                conn.close()
            except Exception:  # noqa: BLE001
                continue

    def _search_sections(
        self,
        scope: Any,
        exact_question: str,
        query_terms: list[str],
        top_k: int,
    ) -> list[SectionCandidate]:
        corpus_ids = [UUID(item) for item in scope.corpus_ids]
        document_ids = [UUID(item) for item in scope.document_ids]
        like_pattern = f"%{exact_question}%"

        query = """
            WITH scoped AS (
                SELECT
                    s.id::text AS section_id,
                    s.document_id::text AS document_id,
                    d.corpus_id::text AS corpus_id,
                    d.file_name,
                    s.page_or_loc,
                    s.section_title,
                    s.section_summary,
                    s.normalized_title,
                    s.normalized_summary,
                    s.search_terms
                FROM doc_sections s
                JOIN documents d ON d.id = s.document_id
                WHERE d.status = 'ready'
                  AND d.corpus_id = ANY(%s::uuid[])
        """
        params: list[Any] = [corpus_ids]
        if document_ids:
            query += " AND d.id = ANY(%s::uuid[])"
            params.append(document_ids)
        query += """
            ),
            scored AS (
                SELECT
                    scoped.*,
                    CASE WHEN scoped.normalized_title LIKE %s THEN 1 ELSE 0 END AS title_exact,
                    CASE WHEN scoped.normalized_summary LIKE %s THEN 1 ELSE 0 END AS summary_exact,
                    similarity(scoped.normalized_title, %s) AS title_similarity,
                    similarity(scoped.normalized_summary, %s) AS summary_similarity,
                    (
                        SELECT COUNT(*)
                        FROM unnest(scoped.search_terms) AS term
                        WHERE term = ANY(%s::text[])
                    ) AS matched_terms
                FROM scoped
                WHERE scoped.search_terms && %s::text[]
                   OR scoped.normalized_title LIKE %s
                   OR scoped.normalized_summary LIKE %s
            )
            SELECT
                section_id,
                document_id,
                corpus_id,
                file_name,
                page_or_loc,
                section_title,
                section_summary,
                (
                    (title_exact * 3.0)
                    + (summary_exact * 2.0)
                    + (matched_terms * 0.6)
                    + (title_similarity * 2.0)
                    + summary_similarity
                )::double precision AS score
            FROM scored
            ORDER BY score DESC, section_id ASC
            LIMIT %s
        """
        params.extend(
            [
                like_pattern,
                like_pattern,
                exact_question,
                exact_question,
                query_terms,
                query_terms,
                like_pattern,
                like_pattern,
                top_k,
            ]
        )

        with self._connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, params)
                rows = cur.fetchall()

        return [
            SectionCandidate(
                section_id=str(row[0]),
                document_id=str(row[1]),
                corpus_id=str(row[2]),
                file_name=str(row[3]),
                page_or_loc=str(row[4]),
                section_title=str(row[5]),
                summary_text=str(row[6]),
                score=float(row[7]),
            )
            for row in rows
        ]

    def _search_chunks(
        self,
        scope: Any,
        *,
        exact_question: str,
        query_terms: list[str],
        top_k: int,
        section_ids: Sequence[str],
    ) -> list[RetrievalResult]:
        corpus_ids = [UUID(item) for item in scope.corpus_ids]
        document_ids = [UUID(item) for item in scope.document_ids]
        like_pattern = f"%{exact_question}%"

        query = """
            WITH scoped AS (
                SELECT
                    c.id::text AS chunk_id,
                    c.document_id::text AS document_id,
                    d.corpus_id::text AS corpus_id,
                    d.file_name,
                    c.page_or_loc,
                    c.chunk_text,
                    c.normalized_text,
                    c.search_terms,
                    c.chunk_index,
                    c.section_id,
                    c.section_title
                FROM doc_chunks c
                JOIN documents d ON d.id = c.document_id
                WHERE d.status = 'ready'
                  AND d.corpus_id = ANY(%s::uuid[])
        """
        params: list[Any] = [corpus_ids]
        if document_ids:
            query += " AND d.id = ANY(%s::uuid[])"
            params.append(document_ids)
        if section_ids:
            query += " AND c.section_id = ANY(%s::text[])"
            params.append(list(section_ids))
        query += """
            ),
            scored AS (
                SELECT
                    scoped.*,
                    CASE WHEN scoped.normalized_text LIKE %s THEN 1 ELSE 0 END AS exact_match,
                    CASE WHEN scoped.section_title <> '' AND similarity(lower(scoped.section_title), %s) > 0.2 THEN 1 ELSE 0 END AS title_hit,
                    similarity(scoped.normalized_text, %s) AS trigram_score,
                    (
                        SELECT COUNT(*)
                        FROM unnest(scoped.search_terms) AS term
                        WHERE term = ANY(%s::text[])
                    ) AS matched_terms,
                    COALESCE(NULLIF(position(%s IN scoped.normalized_text), 0), 2147483647) AS first_pos
                FROM scoped
                WHERE scoped.search_terms && %s::text[]
                   OR scoped.normalized_text LIKE %s
                   OR similarity(scoped.normalized_text, %s) > 0.12
            )
            SELECT
                chunk_id,
                document_id,
                corpus_id,
                file_name,
                page_or_loc,
                chunk_text,
                section_id,
                section_title,
                (
                    (exact_match * 5.0)
                    + (title_hit * 1.5)
                    + (matched_terms * 0.75)
                    + (trigram_score * 2.0)
                    + CASE WHEN first_pos < 2147483647 THEN GREATEST(0, 1.5 - (first_pos / 3000.0)) ELSE 0 END
                )::double precision AS score
            FROM scored
            ORDER BY score DESC, chunk_index ASC
            LIMIT %s
        """
        params.extend(
            [
                like_pattern,
                exact_question,
                exact_question,
                query_terms,
                exact_question,
                query_terms,
                like_pattern,
                exact_question,
                top_k,
            ]
        )

        with self._connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, params)
                rows = cur.fetchall()

        return [
            RetrievalResult(
                chunk_id=str(row[0]),
                document_id=str(row[1]),
                corpus_id=str(row[2]),
                file_name=str(row[3]),
                page_or_loc=str(row[4]),
                text=str(row[5]),
                score=float(row[8]),
                retrieval_type="sparse",
                section_id=str(row[6] or ""),
                section_title=str(row[7] or ""),
                point_type="chunk",
            )
            for row in rows
        ]

    def _build_query_terms(self, question: str) -> list[str]:
        seen: set[str] = set()
        terms: list[str] = []

        def add(candidate: str) -> None:
            normalized = self._normalize(candidate)
            if len(normalized) < 2 or normalized in seen:
                return
            seen.add(normalized)
            terms.append(normalized)

        add(question)
        for token in self._jieba.cut_for_search(question):
            add(str(token))
        for token in ALNUM_TOKEN_RE.findall(question):
            add(token)
        for block in CJK_BLOCK_RE.findall(question):
            add(block)
            upper = min(len(block), 10)
            for size in (2, 3, 4):
                if size > upper:
                    continue
                for idx in range(0, upper - size + 1):
                    add(block[idx : idx + size])

        return terms[:32]

    def _normalize(self, text: str) -> str:
        return WHITESPACE_RE.sub(" ", text).strip().lower()

    def _cache_key(
        self,
        kind: str,
        question: str,
        scope: Any,
        top_k: int,
        section_ids: Sequence[str],
    ) -> str:
        return "|".join(
            [
                kind,
                getattr(scope, "mode", "unknown"),
                ",".join(sorted(scope.corpus_ids)),
                ",".join(sorted(scope.document_ids)),
                ",".join(section_ids),
                question,
                str(top_k),
            ]
        )

    def _cached_payload(self, cache_key: str, top_k: int) -> list[Any] | None:
        cached = self._cache.get(cache_key)
        if cached is None or time() - cached.built_at >= self._ttl_seconds:
            if cached is not None:
                self._cache.pop(cache_key, None)
            return None
        self._cache.move_to_end(cache_key)
        return cached.payload[:top_k]

    def _store_payload(self, cache_key: str, payload: list[Any]) -> None:
        self._cache[cache_key] = CachedSearchResult(built_at=time(), payload=payload)
        self._cache.move_to_end(cache_key)
        while len(self._cache) > self._max_entries:
            self._cache.popitem(last=False)

    def _warm_resources(self) -> None:
        try:
            list(self._jieba.cut_for_search("warmup"))
        except Exception:  # noqa: BLE001
            pass
        try:
            conn = self._create_connection()
        except Exception:  # noqa: BLE001
            return
        self._pool.put(conn)
        self._pool_size = 1

    def _create_connection(self) -> psycopg.Connection:
        conn = psycopg.connect(self._postgres_dsn)
        conn.autocommit = True
        return conn

    @contextmanager
    def _connection(self):
        conn = None
        try:
            try:
                conn = self._pool.get_nowait()
            except Empty:
                with self._pool_lock:
                    if self._pool_size < self._pool.maxsize:
                        conn = self._create_connection()
                        self._pool_size += 1
                if conn is None:
                    conn = self._pool.get(timeout=5)
            yield conn
        finally:
            if conn is None:
                return
            if getattr(conn, "closed", False):
                with self._pool_lock:
                    self._pool_size = max(self._pool_size - 1, 0)
                return
            self._pool.put(conn)
