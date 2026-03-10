#!/usr/bin/env python
from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]
EVAL_LONG_RAG_PATH = REPO_ROOT / "scripts/evaluation/eval-long-rag.py"


def load_eval_module():
    spec = importlib.util.spec_from_file_location("eval_long_rag", EVAL_LONG_RAG_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"unable to load eval module: {EVAL_LONG_RAG_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def write_markdown_report(report: dict[str, Any], output_path: Path) -> None:
    lines = [
        "# Unified Eval Suite Report",
        "",
        "| job | total | accuracy | mrr | ndcg@5 | recall@3 | p95 latency (ms) | refusal precision | refusal recall |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for item in report["jobs"]:
        overall = item["report"]["summary"]["overall"]
        lines.append(
            f"| {item['name']} | {overall['total']} | {overall['accuracy']:.4f} | {overall['mrr']:.4f} | "
            f"{overall['ndcg_at_5']:.4f} | {overall['recall_at_3']:.4f} | {overall['latency']['p95_ms']:.2f} | "
            f"{overall['refusal']['precision']:.4f} | {overall['refusal']['recall']:.4f} |"
        )
    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run multiple unified chat eval jobs from one config file.")
    parser.add_argument("--base-url", default="http://localhost:8080/api/v1")
    parser.add_argument("--email", default="admin@local")
    parser.add_argument("--password", required=True)
    parser.add_argument("--config", required=True)
    parser.add_argument("--output", default="artifacts/reports/eval_suite_report.json")
    parser.add_argument("--summary-output", default="artifacts/reports/eval_suite_report.md")
    args = parser.parse_args()

    module = load_eval_module()
    config = json.loads(Path(args.config).read_text(encoding="utf-8"))
    jobs = config.get("jobs", [])
    if not isinstance(jobs, list) or not jobs:
        raise RuntimeError("suite config must provide a non-empty jobs array")

    results: list[dict[str, Any]] = []
    for job in jobs:
        report = module.run_eval_job(
            base_url=args.base_url,
            email=args.email,
            password=args.password,
            eval_file=str(job["eval_file"]),
            scope_mode=str(job.get("scope_mode", "single")),
            corpus_ids=list(job.get("corpus_ids", [])),
            document_ids=list(job.get("document_ids", [])),
            execution_mode=str(job.get("execution_mode", "grounded")),
        )
        results.append({"name": str(job.get("name") or Path(str(job["eval_file"])).stem), "report": report})

    output = {
        "config": str(Path(args.config).resolve()),
        "jobs": results,
    }
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    summary_path = Path(args.summary_output)
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    write_markdown_report(output, summary_path)
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
