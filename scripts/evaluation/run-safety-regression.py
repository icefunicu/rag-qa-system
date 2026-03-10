#!/usr/bin/env python
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

import httpx

from http_helpers import auth_headers, login


def parse_placeholders(items: list[str]) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for item in items:
        if "=" not in item:
            raise SystemExit(f"invalid --placeholder value: {item!r}; expected KEY=VALUE")
        key, value = item.split("=", 1)
        cleaned_key = key.strip()
        if not cleaned_key:
            raise SystemExit(f"invalid --placeholder key: {item!r}")
        mapping[cleaned_key] = value
    return mapping


def resolve_placeholders(value: Any, placeholders: dict[str, str]) -> Any:
    if isinstance(value, str):
        resolved = value
        for key, replacement in placeholders.items():
            resolved = resolved.replace("${" + key + "}", replacement)
        if "${" in resolved:
            raise RuntimeError(f"unresolved placeholder in fixture value: {resolved}")
        return resolved
    if isinstance(value, list):
        return [resolve_placeholders(item, placeholders) for item in value]
    if isinstance(value, dict):
        return {str(key): resolve_placeholders(item, placeholders) for key, item in value.items()}
    return value


def classify_outcome(safety: dict[str, Any]) -> str:
    if bool(safety.get("blocked")):
        return "blocked"
    if str(safety.get("risk_level") or "").lower() in {"medium", "high"}:
        return "warned"
    return "allowed"


def evaluate_expectations(case: dict[str, Any], *, outcome: str, safety: dict[str, Any]) -> tuple[bool, list[str]]:
    failures: list[str] = []
    expected_outcome = str(case.get("expected_outcome") or "").strip().lower()
    if expected_outcome and expected_outcome != outcome:
        failures.append(f"expected outcome={expected_outcome}, got {outcome}")

    expected_risk_level = str(case.get("expected_risk_level") or "").strip().lower()
    actual_risk_level = str(safety.get("risk_level") or "").strip().lower()
    if expected_risk_level and expected_risk_level != actual_risk_level:
        failures.append(f"expected risk_level={expected_risk_level}, got {actual_risk_level or 'none'}")

    actual_reason_codes = {str(item).strip() for item in list(safety.get("reason_codes") or []) if str(item).strip()}
    for item in list(case.get("expected_reason_codes") or []):
        reason_code = str(item).strip()
        if reason_code and reason_code not in actual_reason_codes:
            failures.append(f"missing reason_code={reason_code}")

    actual_source_types = {str(item).strip() for item in list(safety.get("source_types") or []) if str(item).strip()}
    for item in list(case.get("expected_source_types") or []):
        source_type = str(item).strip()
        if source_type and source_type not in actual_source_types:
            failures.append(f"missing source_type={source_type}")

    return not failures, failures


def run_case(
    client: httpx.Client,
    *,
    query_url: str,
    headers: dict[str, str],
    default_base_id: str,
    case: dict[str, Any],
) -> dict[str, Any]:
    base_id = str(case.get("base_id") or default_base_id).strip()
    if not base_id:
        raise RuntimeError(f"case {case.get('name')!r} is missing base_id")

    payload = {
        "base_id": base_id,
        "question": str(case.get("question") or "").strip(),
        "document_ids": [str(item).strip() for item in list(case.get("document_ids") or []) if str(item).strip()],
    }
    if not payload["question"]:
        raise RuntimeError(f"case {case.get('name')!r} is missing question")

    started = time.perf_counter()
    try:
        response = client.post(query_url, headers=headers, json=payload)
        latency_ms = round((time.perf_counter() - started) * 1000.0, 3)
        response.raise_for_status()
        body = response.json()
        safety = dict(body.get("safety") or {})
        outcome = classify_outcome(safety)
        passed, failures = evaluate_expectations(case, outcome=outcome, safety=safety)
        return {
            "name": str(case.get("name") or ""),
            "ok": True,
            "status_code": int(response.status_code),
            "latency_ms": latency_ms,
            "outcome": outcome,
            "answer_mode": str(body.get("answer_mode") or ""),
            "refusal_reason": str(body.get("refusal_reason") or ""),
            "trace_id": str(body.get("trace_id") or ""),
            "safety": safety,
            "passed": passed,
            "failures": failures,
        }
    except httpx.HTTPStatusError as exc:
        latency_ms = round((time.perf_counter() - started) * 1000.0, 3)
        detail: dict[str, Any] = {}
        try:
            payload = exc.response.json()
            detail = payload if isinstance(payload, dict) else {}
        except Exception:
            detail = {}
        return {
            "name": str(case.get("name") or ""),
            "ok": False,
            "status_code": int(exc.response.status_code),
            "latency_ms": latency_ms,
            "outcome": "error",
            "answer_mode": "",
            "refusal_reason": str(detail.get("code") or "http_error"),
            "trace_id": str(detail.get("trace_id") or ""),
            "safety": {},
            "passed": False,
            "failures": [str(detail.get("detail") or exc.response.text or "request failed")],
        }


def summarize_results(results: list[dict[str, Any]]) -> dict[str, Any]:
    counts = {"allowed": 0, "warned": 0, "blocked": 0, "error": 0}
    for item in results:
        outcome = str(item.get("outcome") or "error")
        counts[outcome] = counts.get(outcome, 0) + 1

    passed = sum(1 for item in results if bool(item.get("passed")))
    latencies = [float(item.get("latency_ms") or 0.0) for item in results]
    return {
        "total_cases": len(results),
        "passed_cases": passed,
        "failed_cases": len(results) - passed,
        "allowed": counts.get("allowed", 0),
        "warned": counts.get("warned", 0),
        "blocked": counts.get("blocked", 0),
        "error": counts.get("error", 0),
        "max_latency_ms": round(max(latencies), 3) if latencies else 0.0,
        "mean_latency_ms": round(sum(latencies) / len(latencies), 3) if latencies else 0.0,
    }


def write_markdown_report(report: dict[str, Any], output_path: Path) -> None:
    summary = report["summary"]
    lines = [
        "# Safety Regression Report",
        "",
        f"- Query endpoint: `{report['config']['query_url']}`",
        f"- Fixture: `{report['config']['fixture']}`",
        f"- Total cases: `{summary['total_cases']}`",
        f"- Passed cases: `{summary['passed_cases']}`",
        f"- Blocked / Warned / Allowed / Error: `{summary['blocked']} / {summary['warned']} / {summary['allowed']} / {summary['error']}`",
        "",
        "| case | outcome | risk | action | reasons | pass | latency ms |",
        "| --- | --- | --- | --- | --- | --- | ---: |",
    ]
    for item in report["results"]:
        safety = dict(item.get("safety") or {})
        lines.append(
            f"| {item['name']} | {item['outcome']} | {safety.get('risk_level', '')} | {safety.get('action', '')} | "
            f"{', '.join(list(safety.get('reason_codes') or []))} | {'yes' if item.get('passed') else 'no'} | {float(item.get('latency_ms') or 0.0):.2f} |"
        )
        if item.get("failures"):
            lines.append(f"|  |  |  |  | failure: {'; '.join(item['failures'])} |  |  |")
    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run prompt safety regression cases against the KB query endpoint.")
    parser.add_argument("--auth-base-url", default="http://localhost:8080/api/v1")
    parser.add_argument("--query-url", default="http://localhost:8300/api/v1/kb/query")
    parser.add_argument("--email", default="admin@local")
    parser.add_argument("--password", required=True)
    parser.add_argument("--base-id", default="")
    parser.add_argument("--fixture", default="scripts/evaluation/fixtures/safety_regression_cases.json")
    parser.add_argument("--placeholder", action="append", default=[], help="placeholder value in KEY=VALUE form")
    parser.add_argument("--output", default="artifacts/reports/safety_regression_report.json")
    parser.add_argument("--summary-output", default="artifacts/reports/safety_regression_report.md")
    args = parser.parse_args()

    placeholders = parse_placeholders(list(args.placeholder))
    if args.base_id:
        placeholders.setdefault("BASE_ID", str(args.base_id))

    fixture_path = Path(args.fixture)
    fixture_payload = json.loads(fixture_path.read_text(encoding="utf-8"))
    resolved_fixture = resolve_placeholders(fixture_payload, placeholders)
    cases = list(resolved_fixture.get("cases") or [])
    if not cases:
        raise SystemExit("fixture must provide a non-empty cases array")

    token = login(args.auth_base_url, args.email, args.password)
    headers = auth_headers(token)

    results: list[dict[str, Any]] = []
    with httpx.Client(timeout=60.0) as client:
        for case in cases:
            results.append(
                run_case(
                    client,
                    query_url=args.query_url,
                    headers=headers,
                    default_base_id=str(args.base_id or ""),
                    case=dict(case),
                )
            )

    report = {
        "config": {
            "auth_base_url": args.auth_base_url,
            "query_url": args.query_url,
            "fixture": str(fixture_path),
            "base_id": str(args.base_id or ""),
            "placeholders": placeholders,
        },
        "summary": summarize_results(results),
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
