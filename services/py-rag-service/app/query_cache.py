from __future__ import annotations

import copy
import hashlib
import threading
import time
from collections import OrderedDict, defaultdict
from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Sequence


@dataclass(frozen=True)
class CachedQuery:
    query_hash: str
    question: str
    result: Any
    created_at: float
    ttl_seconds: int
    hit_count: int = 0
    document_refs: tuple[str, ...] = field(default_factory=tuple)

    def is_expired(self) -> bool:
        return time.time() - self.created_at > self.ttl_seconds


class QueryCache:
    def __init__(
        self,
        max_size: int = 10000,
        ttl_hours: int = 24,
    ):
        self._max_size = max_size
        self._ttl_seconds = ttl_hours * 3600
        self._cache: OrderedDict[str, CachedQuery] = OrderedDict()
        self._document_index: dict[str, set[str]] = defaultdict(set)
        self._hits = 0
        self._misses = 0
        self._lock = threading.RLock()

    def get(self, question: str) -> Optional[Any]:
        query_hash = self._hash_query(question)
        with self._lock:
            cached = self._cache.get(query_hash)
            if cached is None:
                self._misses += 1
                return None

            if cached.is_expired():
                self._evict(query_hash)
                self._misses += 1
                return None

            self._cache.move_to_end(query_hash)
            object.__setattr__(cached, "hit_count", cached.hit_count + 1)
            self._hits += 1
            return copy.deepcopy(cached.result)

    def set(self, question: str, result: Any, document_refs: Sequence[str] | None = None) -> None:
        query_hash = self._hash_query(question)
        refs = tuple(sorted({ref for ref in (document_refs or ()) if ref}))
        cached = CachedQuery(
            query_hash=query_hash,
            question=question,
            result=copy.deepcopy(result),
            created_at=time.time(),
            ttl_seconds=self._ttl_seconds,
            document_refs=refs,
        )

        with self._lock:
            if query_hash in self._cache:
                self._evict(query_hash)

            while len(self._cache) >= self._max_size:
                oldest_key, _ = self._cache.popitem(last=False)
                self._remove_document_links(oldest_key)

            self._cache[query_hash] = cached
            for document_id in refs:
                self._document_index[document_id].add(query_hash)

    def clear(self) -> None:
        with self._lock:
            self._cache.clear()
            self._document_index.clear()
            self._hits = 0
            self._misses = 0

    def invalidate(self, question: str) -> bool:
        query_hash = self._hash_query(question)
        with self._lock:
            if query_hash not in self._cache:
                return False
            self._evict(query_hash)
            return True

    def invalidate_documents(self, document_ids: Sequence[str]) -> int:
        removed = 0
        with self._lock:
            keys: set[str] = set()
            for document_id in document_ids:
                keys.update(self._document_index.get(document_id, set()))
            for key in keys:
                if key in self._cache:
                    self._evict(key)
                    removed += 1
        return removed

    @property
    def size(self) -> int:
        with self._lock:
            return len(self._cache)

    @property
    def hit_rate(self) -> float:
        with self._lock:
            total = self._hits + self._misses
            if total == 0:
                return 0.0
            return self._hits / total

    @property
    def stats(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "size": len(self._cache),
                "max_size": self._max_size,
                "hits": self._hits,
                "misses": self._misses,
                "hit_rate": self.hit_rate,
            }

    def _hash_query(self, question: str) -> str:
        normalized = question.strip().lower()
        return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:32]

    def _evict(self, query_hash: str) -> None:
        self._cache.pop(query_hash, None)
        self._remove_document_links(query_hash)

    def _remove_document_links(self, query_hash: str) -> None:
        empty_keys: list[str] = []
        for document_id, hashes in self._document_index.items():
            hashes.discard(query_hash)
            if not hashes:
                empty_keys.append(document_id)
        for document_id in empty_keys:
            self._document_index.pop(document_id, None)
