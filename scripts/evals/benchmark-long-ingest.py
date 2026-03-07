#!/usr/bin/env python
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any

import httpx


def login(base_url: str, email: str, password: str) -> str:
    with httpx.Client(timeout=30.0) as client:
        resp = client.post(
            f"{base_url.rstrip('/')}/auth/login",
            json={"email": email, "password": password},
        )
        resp.raise_for_status()
        return str(resp.json()["access_token"])


def upload_and_start_ingest(
    base_url: str,
    token: str,
    corpus_id: str,
    file_path: Path,
) -> dict[str, Any]:
    headers = {"Authorization": f"Bearer {token}"}
    with httpx.Client(timeout=120.0) as client:
        upload_meta = client.post(
            f"{base_url.rstrip('/')}/documents/upload-url",
            json={
                "corpus_id": corpus_id,
                "file_name": file_path.name,
                "file_type": file_path.suffix.lstrip(".").lower(),
                "size_bytes": file_path.stat().st_size,
            },
            headers=headers,
        )
        upload_meta.raise_for_status()
        payload = upload_meta.json()

        with file_path.open("rb") as fh:
            put_resp = client.put(payload["upload_url"], content=fh.read(), headers={"Content-Type": "application/octet-stream"})
            put_resp.raise_for_status()

        notify_resp = client.post(
            f"{base_url.rstrip('/')}/documents/upload",
            json={
                "corpus_id": corpus_id,
                "file_name": file_path.name,
                "file_type": file_path.suffix.lstrip(".").lower(),
                "size_bytes": file_path.stat().st_size,
                "storage_key": payload["storage_key"],
            },
            headers=headers,
        )
        notify_resp.raise_for_status()
        return notify_resp.json()


def poll_job(base_url: str, token: str, job_id: str, *, timeout_seconds: int, poll_seconds: float) -> dict[str, Any]:
    headers = {"Authorization": f"Bearer {token}"}
    query_ready_at: float | None = None
    hybrid_ready_at: float | None = None
    late_ready_at: float | None = None
    started = time.time()
    last_payload: dict[str, Any] = {}

    with httpx.Client(timeout=30.0) as client:
        while time.time() - started < timeout_seconds:
            resp = client.get(f"{base_url.rstrip('/')}/ingest-jobs/{job_id}", headers=headers)
            resp.raise_for_status()
            payload = resp.json()
            last_payload = payload

            if payload.get("query_ready") and query_ready_at is None:
                query_ready_at = time.time()
            enhancement_status = str(payload.get("enhancement_status", ""))
            if enhancement_status == "hybrid_ready" and hybrid_ready_at is None:
                hybrid_ready_at = time.time()
            if enhancement_status == "late_interaction_ready" and late_ready_at is None:
                late_ready_at = time.time()
            if payload.get("status") in {"done", "failed", "cancelled", "dead_letter"}:
                break
            time.sleep(poll_seconds)

    finished = time.time()
    return {
        "job": last_payload,
        "timings_seconds": {
            "queryable": round((query_ready_at - started), 3) if query_ready_at else None,
            "hybrid_ready": round((hybrid_ready_at - started), 3) if hybrid_ready_at else None,
            "late_interaction_ready": round((late_ready_at - started), 3) if late_ready_at else None,
            "total": round(finished - started, 3),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Benchmark long-document ingest phases.")
    parser.add_argument("--base-url", default="http://localhost:8080/v1")
    parser.add_argument("--email", default="admin@local")
    parser.add_argument("--password", required=True)
    parser.add_argument("--corpus-id", required=True)
    parser.add_argument("--file", required=True)
    parser.add_argument("--timeout-seconds", type=int, default=900)
    parser.add_argument("--poll-seconds", type=float, default=2.0)
    parser.add_argument("--output", default="docs/reports/long_ingest_report.json")
    args = parser.parse_args()

    file_path = Path(args.file).resolve()
    token = login(args.base_url, args.email, args.password)
    start_payload = upload_and_start_ingest(args.base_url, token, args.corpus_id, file_path)
    result = poll_job(
        args.base_url,
        token,
        start_payload["job_id"],
        timeout_seconds=args.timeout_seconds,
        poll_seconds=args.poll_seconds,
    )
    report = {
        "file": str(file_path),
        "job_id": start_payload["job_id"],
        "document_id": start_payload.get("document_id"),
        **result,
    }

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
