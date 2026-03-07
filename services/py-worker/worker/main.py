from __future__ import annotations

import logging
import os
import signal
import time
from typing import Optional

from redis import Redis
from redis.exceptions import RedisError

from worker.config import build_worker_config
from worker.logger import setup_worker_logger
from worker.processor import IngestProcessor
from worker.runtime_progress import RedisRuntimeProgressTracker


logger = setup_worker_logger(
    level=os.getenv("LOG_LEVEL", "INFO"),
)

# 优雅关闭标志
shutdown_flag: bool = False
current_job_id: Optional[str] = None


def signal_handler(signum, frame):
    """处理 SIGINT 和 SIGTERM 信号"""
    global shutdown_flag
    logger.warning(
        f"Received signal {signum}, initiating graceful shutdown...",
        extra={
            "extra_fields": {
                "signal": signum,
                "current_job": current_job_id,
            }
        },
    )
    shutdown_flag = True


def run() -> None:
    global current_job_id
    
    # 注册信号处理器
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    cfg = build_worker_config()
    redis_cli = Redis.from_url(cfg.redis_url, decode_responses=True)
    processor = IngestProcessor(cfg, progress_tracker=RedisRuntimeProgressTracker(cfg.redis_url))

    logger.info(
        "Worker started",
        extra={
            "extra_fields": {
                "queue": cfg.ingest_queue_key,
                "poll_interval_seconds": cfg.poll_interval_seconds,
                "max_retries": cfg.worker_max_retries,
            }
        },
    )

    while not shutdown_flag:
        try:
            item = redis_cli.blpop(cfg.ingest_queue_key, timeout=cfg.poll_interval_seconds)
            if item is None:
                continue

            _, job_id = item
            current_job_id = job_id
            
            ok, status = processor.process_job(job_id)
            
            log_extra = {
                "job_id": job_id,
                "status": status,
            }
            if ok:
                logger.info(f"Job {job_id} processed successfully", extra=log_extra)
            else:
                logger.warning(f"Job {job_id} processed with status={status}", extra=log_extra)
            
            if status == "retry":
                redis_cli.rpush(cfg.ingest_queue_key, job_id)
            
            current_job_id = None

        except RedisError as exc:
            logger.error(
                "Redis error occurred",
                extra={
                    "extra_fields": {"error": str(exc)},
                },
                exc_info=True,
            )
            time.sleep(cfg.poll_interval_seconds)
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "Unexpected error occurred",
                extra={
                    "extra_fields": {"error": str(exc)},
                },
                exc_info=True,
            )
            time.sleep(cfg.poll_interval_seconds)
    
    # 优雅关闭日志
    if current_job_id:
        logger.info(
            f"Waiting for current job {current_job_id} to complete before shutdown...",
            extra={"job_id": current_job_id},
        )
    logger.info("Worker shutdown complete")


if __name__ == "__main__":
    run()
