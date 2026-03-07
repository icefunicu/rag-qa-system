from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Protocol

from redis import Redis
from redis.exceptions import RedisError


RUNTIME_PROGRESS_KEY_PREFIX = "ingest:runtime_progress:"
DEFAULT_RUNTIME_PROGRESS_TTL_SECONDS = 60 * 60 * 6

logger = logging.getLogger("py-worker")


class RuntimeProgressTracker(Protocol):
    def set(
        self,
        job_id: str,
        *,
        status: str,
        overall_progress: int,
        stage: str,
        message: str = "",
        details: dict[str, Any] | None = None,
    ) -> None:
        ...


class NoopRuntimeProgressTracker:
    def set(
        self,
        job_id: str,
        *,
        status: str,
        overall_progress: int,
        stage: str,
        message: str = "",
        details: dict[str, Any] | None = None,
    ) -> None:
        return


@dataclass(frozen=True)
class RedisRuntimeProgressTracker:
    redis_url: str
    ttl_seconds: int = DEFAULT_RUNTIME_PROGRESS_TTL_SECONDS

    def __post_init__(self) -> None:
        object.__setattr__(self, "_redis", Redis.from_url(self.redis_url, decode_responses=True))

    def set(
        self,
        job_id: str,
        *,
        status: str,
        overall_progress: int,
        stage: str,
        message: str = "",
        details: dict[str, Any] | None = None,
    ) -> None:
        payload: dict[str, Any] = {
            "job_id": job_id,
            "status": status,
            "overall_progress": max(int(overall_progress), 0),
            "stage": stage,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        if message:
            payload["message"] = message
        if details:
            payload["details"] = details

        try:
            self._redis.set(
                self._key(job_id),
                json.dumps(payload, ensure_ascii=False),
                ex=self.ttl_seconds,
            )
        except RedisError as exc:
            logger.debug("runtime progress sync failed: %s", exc)

    @staticmethod
    def _key(job_id: str) -> str:
        return f"{RUNTIME_PROGRESS_KEY_PREFIX}{job_id}"
