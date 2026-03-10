#!/usr/bin/env python
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path
from statistics import mean
from typing import Any

import httpx

from http_helpers import auth_headers, login


REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "packages/python"))

from shared.eval_metrics import summarize_latencies


def write_markdown_report(report: dict[str, Any], output_path: Path) -> None:
    summary = report["summary"]
    lines = [
        "# Retrieval Concurrency Benchmark",
        "",
        f"- Endpoint: `{report['config']['retrieve_url']}`",
        f"- Base ID: `{report['config']['base_id']}`",
        f"- Total requests: `{summary['total_requests']}`",
        f"- Concurrency: `{summary['concurrency']}`",
        "",
        "| metric | value |",
        "| --- | ---: |",
        f"| success rate | {summary['success_rate']:.4f} |",
        f"| throughput (req/s) | {summary['throughput_rps']:.4f} |",
        f"| wall time (s) | {summary['wall_time_seconds']:.4f} |",
        f"| p50 latency (ms) | {summary['latency']['p50_ms']:.2f} |",
        f"| p95 latency (ms) | {summary['latency']['p95_ms']:.2f} |",
        f"| max latency (ms) | {summary['latency']['max_ms']:.2f} |",
        f"| mean retrieval ms | {summary['retrieval_ms']['mean_ms']:.2f} |",
        f"| p95 retrieval ms | {summary['retrieval_ms']['p95_ms']:.2f} |",
        f"| mean selected candidates | {summary['mean_selected_candidates']:.2f} |",
        f"| error count | {summary['error_count']} |",
    ]
    if report["errors"]:
        lines.extend(
            [
                "",
                "## Errors",
                "",
                "| status | code | count |",
                "| --- | --- | ---: |",
            ]
        )
        for item in report["errors"]:
            lines.append(f"| {item['status_code']} | {item['code']} | {item['count']} |")
    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


async def send_request(
    client: httpx.AsyncClient,
    *,
    retrieve_url: str,
    headers: dict[str, str],
    payload: dict[str, Any],
    request_id: int,
) -> dict[str, Any]:
    started = time.perf_counter()
    try:
        response = await client.post(retrieve_url, headers=headers, json=payload)
        latency_ms = round((time.perf_counter() - started) * 1000.0, 4)
        response.raise_for_status()
        body = response.json()
        retrieval = dict(body.get("retrieval") or {})
        return {
            "request_id": request_id,
            "ok": True,
            "status_code": response.status_code,
            "latency_ms": latency_ms,
            "trace_id": str(body.get("trace_id") or ""),
            "selected_candidates": int(retrieval.get("selected_candidates", 0) or 0),
            "retrieval_ms": float(retrieval.get("retrieval_ms", 0.0) or 0.0),
            "error": {},
        }
    except httpx.HTTPStatusError as exc:
        latency_ms = round((time.perf_counter() - started) * 1000.0, 4)
        detail: dict[str, Any] = {}
        try:
            payload = exc.response.json()
            detail = payload if isinstance(payload, dict) else {}
        except Exception:
            detail = {}
        return {
            "request_id": request_id,
            "ok": False,
            "status_code": exc.response.status_code,
            "latency_ms": latency_ms,
            "trace_id": "",
            "selected_candidates": 0,
            "retrieval_ms": 0.0,
            "error": {
                "code": str(detail.get("code") or "http_error"),
                "detail": str(detail.get("detail") or exc.response.text or "request failed"),
            },
        }
    except Exception as exc:
        latency_ms = round((time.perf_counter() - started) * 1000.0, 4)
        return {
            "request_id": request_id,
            "ok": False,
            "status_code": 0,
            "latency_ms": latency_ms,
            "trace_id": "",
            "selected_candidates": 0,
            "retrieval_ms": 0.0,
            "error": {
                "code": exc.__class__.__name__,
                "detail": str(exc),
            },
        }


async def run_concurrency_benchmark(
    *,
    retrieve_url: str,
    headers: dict[str, str],
    payload: dict[str, Any],
    total_requests: int,
    concurrency: int,
    timeout_seconds: float,
) -> tuple[list[dict[str, Any]], float]:
    limits = httpx.Limits(max_keepalive_connections=concurrency, max_connections=max(concurrency * 2, 4))
    async with httpx.AsyncClient(timeout=timeout_seconds, limits=limits) as client:
        started = time.perf_counter()
        tasks = [
            send_request(
                client,
                retrieve_url=retrieve_url,
                headers=headers,
                payload=payload,
                request_id=request_id,
            )
            for request_id in range(1, total_requests + 1)
        ]

        results: list[dict[str, Any]] = []
        for chunk_start in range(0, len(tasks), concurrency):
            chunk = tasks[chunk_start : chunk_start + concurrency]
            results.extend(await asyncio.gather(*chunk))
        wall_time_seconds = round(time.perf_counter() - started, 4)
        return results, wall_time_seconds


def summarize_results(
    *,
    total_requests: int,
    concurrency: int,
    wall_time_seconds: float,
    results: list[dict[str, Any]],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    success_rows = [item for item in results if item["ok"]]
    error_rows = [item for item in results if not item["ok"]]
    latency_values = [float(item["latency_ms"]) for item in results]
    retrieval_values = [float(item["retrieval_ms"]) for item in success_rows if float(item["retrieval_ms"]) > 0]
    selected_candidates = [int(item["selected_candidates"]) for item in success_rows]

    error_counts: dict[tuple[int, str], int] = {}
    for item in error_rows:
        key = (int(item["status_code"]), str(item["error"].get("code") or "unknown_error"))
        error_counts[key] = error_counts.get(key, 0) + 1

    errors = [
        {"status_code": status_code, "code": code, "count": count}
        for (status_code, code), count in sorted(error_counts.items(), key=lambda item: (-item[1], item[0][0], item[0][1]))
    ]
    summary = {
        "total_requests": total_requests,
        "concurrency": concurrency,
        "success_count": len(success_rows),
        "error_count": len(error_rows),
        "success_rate": round(len(success_rows) / float(total_requests), 4) if total_requests else 0.0,
        "throughput_rps": round(len(results) / wall_time_seconds, 4) if wall_time_seconds > 0 else 0.0,
        "wall_time_seconds": wall_time_seconds,
        "latency": summarize_latencies(latency_values),
        "retrieval_ms": summarize_latencies(retrieval_values),
        "mean_selected_candidates": round(mean(selected_candidates), 4) if selected_candidates else 0.0,
    }
    return summary, errors


def warmup(
    *,
    retrieve_url: str,
    headers: dict[str, str],
    payload: dict[str, Any],
    requests: int,
    timeout_seconds: float,
) -> None:
    if requests <= 0:
        return
    with httpx.Client(timeout=timeout_seconds) as client:
        for _ in range(requests):
            response = client.post(retrieve_url, headers=headers, json=payload)
            response.raise_for_status()


def main() -> int:
    parser = argparse.ArgumentParser(description="Benchmark KB retrieval latency and throughput under concurrent load.")
    parser.add_argument("--auth-base-url", default="http://localhost:8080/api/v1")
    parser.add_argument("--retrieve-url", default="http://localhost:8300/api/v1/kb/retrieve")
    parser.add_argument("--email", default="admin@local")
    parser.add_argument("--password", required=True)
    parser.add_argument("--base-id", required=True)
    parser.add_argument("--question", required=True)
    parser.add_argument("--document-id", action="append", default=[])
    parser.add_argument("--limit", type=int, default=8)
    parser.add_argument("--total-requests", type=int, default=40)
    parser.add_argument("--concurrency", type=int, default=8)
    parser.add_argument("--warmup-requests", type=int, default=2)
    parser.add_argument("--timeout-seconds", type=float, default=60.0)
    parser.add_argument("--output", default="artifacts/reports/retrieval_concurrency_benchmark.json")
    parser.add_argument("--summary-output", default="artifacts/reports/retrieval_concurrency_benchmark.md")
    args = parser.parse_args()

    if args.total_requests <= 0:
        raise SystemExit("--total-requests must be > 0")
    if args.concurrency <= 0:
        raise SystemExit("--concurrency must be > 0")

    token = login(args.auth_base_url, args.email, args.password)
    headers = auth_headers(token)
    payload = {
        "base_id": args.base_id,
        "question": args.question,
        "document_ids": [str(item) for item in args.document_id if str(item).strip()],
        "limit": max(int(args.limit), 1),
    }

    warmup(
        retrieve_url=args.retrieve_url,
        headers=headers,
        payload=payload,
        requests=max(int(args.warmup_requests), 0),
        timeout_seconds=max(float(args.timeout_seconds), 5.0),
    )

    results, wall_time_seconds = asyncio.run(
        run_concurrency_benchmark(
            retrieve_url=args.retrieve_url,
            headers=headers,
            payload=payload,
            total_requests=int(args.total_requests),
            concurrency=int(args.concurrency),
            timeout_seconds=max(float(args.timeout_seconds), 5.0),
        )
    )
    summary, errors = summarize_results(
        total_requests=int(args.total_requests),
        concurrency=int(args.concurrency),
        wall_time_seconds=wall_time_seconds,
        results=results,
    )
    report = {
        "config": {
            "auth_base_url": args.auth_base_url,
            "retrieve_url": args.retrieve_url,
            "base_id": args.base_id,
            "question": args.question,
            "document_ids": payload["document_ids"],
            "limit": payload["limit"],
            "total_requests": int(args.total_requests),
            "concurrency": int(args.concurrency),
            "warmup_requests": int(args.warmup_requests),
            "timeout_seconds": max(float(args.timeout_seconds), 5.0),
        },
        "summary": summary,
        "errors": errors,
        "results": results,
    }

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    summary_path = Path(args.summary_output)
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    write_markdown_report(report, summary_path)

    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
