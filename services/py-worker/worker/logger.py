"""
Worker 结构化日志配置
"""
import logging
import sys
from datetime import datetime, timezone
import json
from typing import Any, Dict


def setup_worker_logger(
    name: str = "py-worker",
    level: str = "INFO",
) -> logging.Logger:
    """
    设置 Worker 的日志记录器

    Args:
        name: 日志记录器名称
        level: 日志级别

    Returns:
        配置好的 Logger 实例
    """
    logger = logging.getLogger(name)
    logger.setLevel(getattr(logging, level.upper(), logging.INFO))

    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setLevel(getattr(logging, level.upper(), logging.INFO))

        formatter = WorkerJsonFormatter()
        handler.setFormatter(formatter)
        logger.addHandler(handler)

    return logger


class WorkerJsonFormatter(logging.Formatter):
    """
    Worker JSON 日志 Formatter
    输出格式:
    {
        "timestamp": "2026-03-05T12:34:56.789Z",
        "level": "INFO",
        "service": "py-worker",
        "logger": "py-worker",
        "message": "job=xxx processed ok=True status=success",
        "job_id": "xxx-xxx-xxx",
        "status": "success"
    }
    """

    def __init__(self):
        super().__init__()
        self.service_name = "py-worker"

    def format(self, record: logging.LogRecord) -> str:
        log_data: Dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "level": record.levelname,
            "service": self.service_name,
            "logger": record.name,
            "message": record.getMessage(),
        }

        if hasattr(record, "job_id"):
            log_data["job_id"] = record.job_id

        if hasattr(record, "status"):
            log_data["status"] = record.status

        if hasattr(record, "queue"):
            log_data["queue"] = record.queue

        if hasattr(record, "extra_fields"):
            log_data.update(record.extra_fields)

        if record.exc_info:
            log_data["exception"] = {
                "type": record.exc_info[0].__name__ if record.exc_info[0] else "Unknown",
                "message": str(record.exc_info[1]) if record.exc_info[1] else "",
                "traceback": self.formatException(record.exc_info),
            }

        return json.dumps(log_data, ensure_ascii=False)
