#!/usr/bin/env python
from __future__ import annotations

import argparse
import json
from collections import defaultdict
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


def load_eval_cases(path: Path) -> list[dict[str, Any]]:
    return json.loads(path.read_text(encoding="utf-8"))


def score_case(case: dict[str, Any], response: dict[str, Any]) -> dict[str, Any]:
    citations = response.get("citations", []) or []
    section_titles = [str(item.get("section_title", "")) for item in citations]
    expected = [str(item) for item in case.get("expected_sections", [])]
    hits = 0
    for target in expected:
        if any(target and target in actual for actual in section_titles):
            hits += 1

    evidence_status = str(response.get("evidence_status", ""))
    answer_mode = str(response.get("answer_mode", ""))
    grounded = evidence_status in {"grounded", "tentative"}
    citation_ok = len(citations) >= int(case.get("min_citations", 0))
    matched = hits > 0 and citation_ok
    refused = answer_mode == "refusal"
    should_refuse = bool(case.get("must_refuse_without_evidence", False)) and not matched
    return {
        "id": case["id"],
        "category": case["category"],
        "matched": matched,
        "expected_hits": hits,
        "citation_count": len(citations),
        "evidence_status": evidence_status,
        "answer_mode": answer_mode,
        "grounded": grounded,
        "refused_when_expected": refused if should_refuse else None,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate long-document RAG behavior.")
    parser.add_argument("--base-url", default="http://localhost:8080/v1")
    parser.add_argument("--email", default="admin@local")
    parser.add_argument("--password", required=True)
    parser.add_argument("--eval-file", default="tests/evals/novel-large-doc-eval.json")
    parser.add_argument("--corpus-id", required=True)
    parser.add_argument("--document-id", action="append", default=[])
    parser.add_argument("--output", default="docs/reports/long_rag_eval_report.json")
    args = parser.parse_args()

    token = login(args.base_url, args.email, args.password)
    headers = {"Authorization": f"Bearer {token}"}
    scope = {
        "mode": "single",
        "corpus_ids": [args.corpus_id],
        "document_ids": args.document_id,
        "allow_common_knowledge": False,
    }

    cases = load_eval_cases(Path(args.eval_file))
    results: list[dict[str, Any]] = []
    by_category: dict[str, dict[str, int]] = defaultdict(lambda: {"total": 0, "matched": 0})

    with httpx.Client(timeout=120.0) as client:
        for case in cases:
            resp = client.post(
                f"{args.base_url.rstrip('/')}/chat/sessions",
                json={"title": "eval"},
                headers=headers,
            )
            resp.raise_for_status()
            session_id = resp.json()["session_id"]

            msg_resp = client.post(
                f"{args.base_url.rstrip('/')}/chat/sessions/{session_id}/messages",
                json={"question": case["question"], "scope": scope},
                headers=headers,
            )
            msg_resp.raise_for_status()
            payload = msg_resp.json()
            scored = score_case(case, payload)
            results.append(scored)
            by_category[case["category"]]["total"] += 1
            if scored["matched"]:
                by_category[case["category"]]["matched"] += 1

    summary = {
        category: {
            "matched": stats["matched"],
            "total": stats["total"],
            "accuracy": round(stats["matched"] / stats["total"], 4) if stats["total"] else 0.0,
        }
        for category, stats in by_category.items()
    }
    report = {
        "eval_file": str(Path(args.eval_file).resolve()),
        "corpus_id": args.corpus_id,
        "document_ids": args.document_id,
        "summary": summary,
        "results": results,
    }

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
