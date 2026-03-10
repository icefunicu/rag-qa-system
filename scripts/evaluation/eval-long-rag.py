#!/usr/bin/env python
from __future__ import annotations

import argparse
import json
import sys
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

import httpx


REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "packages/python"))

from shared.eval_metrics import ndcg_at_k, precision, recall_at_k, reciprocal_rank, refusal_scores, summarize_latencies


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


def build_scope(mode: str, corpus_ids: list[str], document_ids: list[str]) -> dict[str, Any]:
    return {
        "mode": mode,
        "corpus_ids": corpus_ids,
        "document_ids": document_ids,
        "allow_common_knowledge": False,
    }


def rank_relevance(case: dict[str, Any], response: dict[str, Any]) -> tuple[list[int], int]:
    citations = response.get("citations", []) or []
    expected = [str(item) for item in case.get("expected_sections", [])]
    relevance: list[int] = []
    expected_hits = 0
    for citation in citations:
        section_title = str(citation.get("section_title", "") or "")
        hit = 1 if any(target and target in section_title for target in expected) else 0
        relevance.append(hit)
        expected_hits += hit
    return relevance, expected_hits


def score_case(case: dict[str, Any], response: dict[str, Any], *, latency_ms: float) -> dict[str, Any]:
    citations = response.get("citations", []) or []
    evidence_status = str(response.get("evidence_status", ""))
    answer_mode = str(response.get("answer_mode", ""))
    retrieval = dict(response.get("retrieval") or {})
    relevance, expected_hits = rank_relevance(case, response)
    min_citations = int(case.get("min_citations", 0) or 0)
    citation_ok = len(citations) >= min_citations
    matched = expected_hits > 0 and citation_ok
    expected_refusal = bool(case.get("must_refuse_without_evidence", False)) and not matched
    refused = answer_mode == "refusal"
    return {
        "id": str(case.get("id") or ""),
        "category": str(case.get("category") or "default"),
        "matched": matched,
        "expected_hits": expected_hits,
        "citation_count": len(citations),
        "citation_precision": precision(sum(1 for item in relevance if item > 0), len(relevance)),
        "recall_at_1": recall_at_k(relevance, 1),
        "recall_at_3": recall_at_k(relevance, 3),
        "recall_at_5": recall_at_k(relevance, 5),
        "mrr": reciprocal_rank(relevance),
        "ndcg_at_5": ndcg_at_k(relevance, 5),
        "evidence_status": evidence_status,
        "answer_mode": answer_mode,
        "grounding_score": float(response.get("grounding_score", 0) or 0),
        "expected_refusal": expected_refusal,
        "refused": refused,
        "refused_when_expected": refused if expected_refusal else None,
        "latency_ms": round(latency_ms, 4),
        "trace_id": str(response.get("trace_id") or ""),
        "retrieval": retrieval,
    }


def summarize_results(results: list[dict[str, Any]]) -> dict[str, Any]:
    by_category: dict[str, dict[str, list[float] | int]] = defaultdict(
        lambda: {
            "total": 0,
            "matched": 0,
            "latencies": [],
            "mrr": [],
            "ndcg": [],
            "recall_at_1": [],
            "recall_at_3": [],
            "recall_at_5": [],
            "citation_precision": [],
        }
    )
    refusal_tp = 0
    refusal_fp = 0
    refusal_fn = 0
    latencies: list[float] = []
    mrr_values: list[float] = []
    ndcg_values: list[float] = []
    recall_1_values: list[float] = []
    recall_3_values: list[float] = []
    recall_5_values: list[float] = []
    citation_precision_values: list[float] = []
    retrieval_ms_values: list[float] = []
    selected_candidate_values: list[float] = []

    for result in results:
        category = str(result["category"])
        by_category[category]["total"] += 1
        by_category[category]["matched"] += 1 if result["matched"] else 0
        by_category[category]["latencies"].append(float(result["latency_ms"]))
        by_category[category]["mrr"].append(float(result["mrr"]))
        by_category[category]["ndcg"].append(float(result["ndcg_at_5"]))
        by_category[category]["recall_at_1"].append(float(result["recall_at_1"]))
        by_category[category]["recall_at_3"].append(float(result["recall_at_3"]))
        by_category[category]["recall_at_5"].append(float(result["recall_at_5"]))
        by_category[category]["citation_precision"].append(float(result["citation_precision"]))

        latencies.append(float(result["latency_ms"]))
        mrr_values.append(float(result["mrr"]))
        ndcg_values.append(float(result["ndcg_at_5"]))
        recall_1_values.append(float(result["recall_at_1"]))
        recall_3_values.append(float(result["recall_at_3"]))
        recall_5_values.append(float(result["recall_at_5"]))
        citation_precision_values.append(float(result["citation_precision"]))

        retrieval = dict(result.get("retrieval") or {})
        retrieval_ms_values.append(float(retrieval.get("aggregate", {}).get("retrieval_ms", retrieval.get("retrieval_ms", 0.0)) or 0.0))
        selected_candidate_values.append(
            float(retrieval.get("aggregate", {}).get("selected_candidates", retrieval.get("selected_candidates", 0)) or 0.0)
        )

        expected_refusal = bool(result.get("expected_refusal"))
        refused = bool(result.get("refused"))
        if expected_refusal and refused:
            refusal_tp += 1
        elif not expected_refusal and refused:
            refusal_fp += 1
        elif expected_refusal and not refused:
            refusal_fn += 1

    per_category = {
        category: {
            "matched": int(stats["matched"]),
            "total": int(stats["total"]),
            "accuracy": round((int(stats["matched"]) / int(stats["total"])), 4) if int(stats["total"]) else 0.0,
            "mrr": round(sum(stats["mrr"]) / len(stats["mrr"]), 4) if stats["mrr"] else 0.0,
            "ndcg_at_5": round(sum(stats["ndcg"]) / len(stats["ndcg"]), 4) if stats["ndcg"] else 0.0,
            "recall_at_1": round(sum(stats["recall_at_1"]) / len(stats["recall_at_1"]), 4) if stats["recall_at_1"] else 0.0,
            "recall_at_3": round(sum(stats["recall_at_3"]) / len(stats["recall_at_3"]), 4) if stats["recall_at_3"] else 0.0,
            "recall_at_5": round(sum(stats["recall_at_5"]) / len(stats["recall_at_5"]), 4) if stats["recall_at_5"] else 0.0,
            "citation_precision": round(sum(stats["citation_precision"]) / len(stats["citation_precision"]), 4)
            if stats["citation_precision"]
            else 0.0,
            "latency": summarize_latencies(stats["latencies"]),
        }
        for category, stats in by_category.items()
    }
    return {
        "overall": {
            "total": len(results),
            "accuracy": round(sum(1 for item in results if item["matched"]) / len(results), 4) if results else 0.0,
            "mrr": round(sum(mrr_values) / len(mrr_values), 4) if mrr_values else 0.0,
            "ndcg_at_5": round(sum(ndcg_values) / len(ndcg_values), 4) if ndcg_values else 0.0,
            "recall_at_1": round(sum(recall_1_values) / len(recall_1_values), 4) if recall_1_values else 0.0,
            "recall_at_3": round(sum(recall_3_values) / len(recall_3_values), 4) if recall_3_values else 0.0,
            "recall_at_5": round(sum(recall_5_values) / len(recall_5_values), 4) if recall_5_values else 0.0,
            "citation_precision": round(sum(citation_precision_values) / len(citation_precision_values), 4)
            if citation_precision_values
            else 0.0,
            "latency": summarize_latencies(latencies),
            "retrieval": {
                "mean_ms": round(sum(retrieval_ms_values) / len(retrieval_ms_values), 4) if retrieval_ms_values else 0.0,
                "mean_selected_candidates": round(sum(selected_candidate_values) / len(selected_candidate_values), 4)
                if selected_candidate_values
                else 0.0,
            },
            "refusal": refusal_scores(
                true_positive=refusal_tp,
                false_positive=refusal_fp,
                false_negative=refusal_fn,
            ),
        },
        "by_category": per_category,
    }


def write_markdown_report(report: dict[str, Any], output_path: Path) -> None:
    summary = report["summary"]["overall"]
    lines = [
        "# Unified Chat Eval Report",
        "",
        f"- Eval file: `{report['eval_file']}`",
        f"- Scope mode: `{report['scope_mode']}`",
        f"- Execution mode: `{report['execution_mode']}`",
        f"- Corpus IDs: `{', '.join(report['corpus_ids'])}`",
        "",
        "## Overall",
        "",
        "| metric | value |",
        "| --- | ---: |",
        f"| accuracy | {summary['accuracy']:.4f} |",
        f"| mrr | {summary['mrr']:.4f} |",
        f"| ndcg@5 | {summary['ndcg_at_5']:.4f} |",
        f"| recall@1 | {summary['recall_at_1']:.4f} |",
        f"| recall@3 | {summary['recall_at_3']:.4f} |",
        f"| recall@5 | {summary['recall_at_5']:.4f} |",
        f"| citation precision | {summary['citation_precision']:.4f} |",
        f"| latency p50 (ms) | {summary['latency']['p50_ms']:.2f} |",
        f"| latency p95 (ms) | {summary['latency']['p95_ms']:.2f} |",
        f"| mean retrieval ms | {summary['retrieval']['mean_ms']:.2f} |",
        f"| mean selected candidates | {summary['retrieval']['mean_selected_candidates']:.2f} |",
        f"| refusal precision | {summary['refusal']['precision']:.4f} |",
        f"| refusal recall | {summary['refusal']['recall']:.4f} |",
        "",
        "## By Category",
        "",
        "| category | accuracy | mrr | ndcg@5 | recall@3 | citation precision | p95 latency (ms) |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for category, metrics in report["summary"]["by_category"].items():
        lines.append(
            f"| {category} | {metrics['accuracy']:.4f} | {metrics['mrr']:.4f} | {metrics['ndcg_at_5']:.4f} | "
            f"{metrics['recall_at_3']:.4f} | {metrics['citation_precision']:.4f} | {metrics['latency']['p95_ms']:.2f} |"
        )
    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run_eval_job(
    *,
    base_url: str,
    email: str,
    password: str,
    eval_file: str,
    scope_mode: str,
    corpus_ids: list[str],
    document_ids: list[str],
    execution_mode: str = "grounded",
) -> dict[str, Any]:
    token = login(base_url, email, password)
    headers = {"Authorization": f"Bearer {token}"}
    scope = build_scope(scope_mode, corpus_ids, document_ids)
    cases = load_eval_cases(Path(eval_file))
    results: list[dict[str, Any]] = []

    with httpx.Client(timeout=120.0) as client:
        session_response = client.post(
            f"{base_url.rstrip('/')}/chat/sessions",
            json={"title": f"eval-{scope_mode}", "scope": scope, "execution_mode": execution_mode},
            headers=headers,
        )
        session_response.raise_for_status()
        session_id = session_response.json()["session_id"]

        for case in cases:
            started = time.perf_counter()
            msg_resp = client.post(
                f"{base_url.rstrip('/')}/chat/sessions/{session_id}/messages",
                json={"question": case["question"], "scope": scope, "execution_mode": execution_mode},
                headers=headers,
            )
            msg_resp.raise_for_status()
            latency_ms = (time.perf_counter() - started) * 1000.0
            payload = msg_resp.json()
            results.append(score_case(case, payload, latency_ms=latency_ms))

    report = {
        "eval_file": str(Path(eval_file).resolve()),
        "scope_mode": scope_mode,
        "corpus_ids": corpus_ids,
        "document_ids": document_ids,
        "execution_mode": execution_mode,
        "summary": summarize_results(results),
        "results": results,
    }
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate unified chat RAG behavior.")
    parser.add_argument("--base-url", default="http://localhost:8080/api/v1")
    parser.add_argument("--email", default="admin@local")
    parser.add_argument("--password", required=True)
    parser.add_argument("--eval-file", required=True)
    parser.add_argument("--scope-mode", choices=["single", "multi", "all"], default="single")
    parser.add_argument("--corpus-id", action="append", default=[], help="repeatable; format kb:<uuid>")
    parser.add_argument("--document-id", action="append", default=[])
    parser.add_argument("--execution-mode", choices=["grounded", "agent"], default="grounded")
    parser.add_argument("--output", default="artifacts/reports/long_rag_eval_report.json")
    parser.add_argument("--summary-output", default="artifacts/reports/long_rag_eval_report.md")
    args = parser.parse_args()

    report = run_eval_job(
        base_url=args.base_url,
        email=args.email,
        password=args.password,
        eval_file=args.eval_file,
        scope_mode=args.scope_mode,
        corpus_ids=args.corpus_id,
        document_ids=args.document_id,
        execution_mode=args.execution_mode,
    )
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
