from __future__ import annotations

import os
import time
from dataclasses import dataclass
from datetime import datetime, timezone


@dataclass(frozen=True)
class WorkerConfig:
    redis_url: str
    poll_interval_seconds: int


def build_worker_config() -> WorkerConfig:
    redis_url = os.getenv("REDIS_URL", "redis://redis:6379/0")
    poll_interval_seconds = int(os.getenv("WORKER_POLL_INTERVAL_SECONDS", "5"))
    if poll_interval_seconds <= 0:
        poll_interval_seconds = 5
    return WorkerConfig(redis_url=redis_url, poll_interval_seconds=poll_interval_seconds)


def run() -> None:
    cfg = build_worker_config()
    print(
        f"[py-worker] started; redis_url={cfg.redis_url}; poll_interval={cfg.poll_interval_seconds}s",
        flush=True,
    )

    while True:
        now = datetime.now(tz=timezone.utc).isoformat()
        # Phase 1 占位循环：后续将接入 ingest job 队列消费。
        print(f"[py-worker] heartbeat at {now}", flush=True)
        time.sleep(cfg.poll_interval_seconds)


if __name__ == "__main__":
    run()

