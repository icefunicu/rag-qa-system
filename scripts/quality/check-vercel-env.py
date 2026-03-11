#!/usr/bin/env python3
"""Validate the Vercel showcase environment template."""

from __future__ import annotations

import sys
from pathlib import Path


REQUIRED_KEYS = {
    "APP_ENV",
    "JWT_SECRET",
    "ADMIN_EMAIL",
    "ADMIN_PASSWORD",
    "MEMBER_EMAIL",
    "MEMBER_PASSWORD",
    "KB_SERVICE_URL",
    "VITE_GATEWAY_ORIGIN",
    "KB_DATABASE_DSN",
    "GATEWAY_DATABASE_DSN",
    "OBJECT_STORAGE_ENDPOINT",
    "OBJECT_STORAGE_PUBLIC_ENDPOINT",
    "OBJECT_STORAGE_ACCESS_KEY",
    "OBJECT_STORAGE_SECRET_KEY",
    "OBJECT_STORAGE_BUCKET",
    "QDRANT_URL",
    "QDRANT_API_KEY",
    "LLM_PROVIDER",
    "LLM_BASE_URL",
    "LLM_API_KEY",
    "LLM_MODEL",
    "EMBEDDING_PROVIDER",
    "EMBEDDING_API_URL",
    "EMBEDDING_API_KEY",
    "EMBEDDING_MODEL",
    "RERANK_PROVIDER",
    "RERANK_API_BASE_URL",
    "RERANK_API_KEY",
    "RERANK_MODEL",
    "VISION_PROVIDER",
    "VISION_FALLBACK_PROVIDER",
    "VISION_API_BASE_URL",
    "VISION_API_KEY",
    "VISION_MODEL",
}

EXPECTED_VALUES = {
    "APP_ENV": "production",
    "EMBEDDING_PROVIDER": "external",
    "RERANK_PROVIDER": "cross-encoder",
    "VISION_PROVIDER": "external",
    "VISION_FALLBACK_PROVIDER": "external",
}

HTTPS_KEYS = {
    "KB_SERVICE_URL",
    "VITE_GATEWAY_ORIGIN",
    "OBJECT_STORAGE_ENDPOINT",
    "OBJECT_STORAGE_PUBLIC_ENDPOINT",
    "QDRANT_URL",
    "LLM_BASE_URL",
    "EMBEDDING_API_URL",
    "RERANK_API_BASE_URL",
    "VISION_API_BASE_URL",
}

FORBIDDEN_MARKERS = {
    "localhost",
    "127.0.0.1",
    "::1",
    "postgres:5432",
    "gateway:",
    "kb-service:",
    "minio:",
    "qdrant:",
    "/data/kb",
}

SENSITIVE_DEFAULTS = {
    "JWT_SECRET": {"change-me-in-env", "replace-this-in-local-env", "replace-with-local-random-secret"},
    "ADMIN_PASSWORD": {"ChangeMe123!"},
    "MEMBER_PASSWORD": {"ChangeMe123!"},
}


def load_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in raw_line:
            raise ValueError(f"{path}:{line_number} 缺少 '=': {raw_line}")
        key, _, value = raw_line.partition("=")
        key = key.strip()
        if not key:
            raise ValueError(f"{path}:{line_number} 存在空变量名")
        values[key] = value.strip()
    return values


def validate(values: dict[str, str]) -> list[str]:
    failures: list[str] = []

    missing_keys = sorted(key for key in REQUIRED_KEYS if not values.get(key, "").strip())
    for key in missing_keys:
        failures.append(f"缺少必填项: {key}")

    for key, expected in EXPECTED_VALUES.items():
        actual = values.get(key, "").strip().lower()
        if actual and actual != expected:
            failures.append(f"{key} 必须为 {expected}，当前为 {values.get(key, '').strip()}")

    for key in HTTPS_KEYS:
        value = values.get(key, "").strip()
        if value and not value.startswith("https://"):
            failures.append(f"{key} 必须使用 https:// 外部地址，当前为 {value}")

    for key in ("KB_DATABASE_DSN", "GATEWAY_DATABASE_DSN"):
        value = values.get(key, "").strip().lower()
        if value and not value.startswith("postgresql://"):
            failures.append(f"{key} 必须使用 postgresql:// DSN，当前为 {values.get(key, '').strip()}")

    for key, disallowed in SENSITIVE_DEFAULTS.items():
        value = values.get(key, "").strip()
        if value in disallowed:
            failures.append(f"{key} 不能沿用本地默认占位值")

    endpoint_keys = HTTPS_KEYS | {"KB_DATABASE_DSN", "GATEWAY_DATABASE_DSN"}
    for key in sorted(endpoint_keys):
        value = values.get(key, "").strip().lower()
        if not value:
            continue
        for marker in FORBIDDEN_MARKERS:
            if marker in value:
                failures.append(f"{key} 不能指向本地或容器内资源: 命中 {marker}")
                break

    return failures


def main() -> int:
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(".env.vercel.example")
    if not target.is_file():
        print(f"Vercel env check failed: file not found: {target}")
        return 1
    try:
        values = load_env_file(target)
    except ValueError as exc:
        print(f"Vercel env check failed: {exc}")
        return 1

    failures = validate(values)
    if failures:
        print("Vercel env check failed:")
        for failure in failures:
            print(f"  - {failure}")
        return 1

    print(f"Vercel env check passed: {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
