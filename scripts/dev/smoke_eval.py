from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import httpx


REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURE_DIR = REPO_ROOT / "scripts" / "evaluation" / "fixtures"
REPORT_DIR = REPO_ROOT / "artifacts" / "reports"
EVAL_SUITE_SCRIPT = REPO_ROOT / "scripts" / "evaluation" / "run-eval-suite.py"


def load_env_file() -> dict[str, str]:
    env_path = REPO_ROOT / ".env"
    values: dict[str, str] = {}
    if not env_path.exists():
        return values
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def login(base_url: str, email: str, password: str) -> str:
    with httpx.Client(timeout=30.0) as client:
        response = client.post(
            f"{base_url.rstrip('/')}/auth/login",
            json={"email": email, "password": password},
        )
        response.raise_for_status()
        return str(response.json()["access_token"])


def create_base(client: httpx.Client, api_base: str, token: str, name: str, description: str) -> str:
    response = client.post(
        f"{api_base}/kb/bases",
        headers={"Authorization": f"Bearer {token}"},
        json={"name": name, "description": description, "category": "smoke-eval"},
    )
    response.raise_for_status()
    return str(response.json()["id"])


def upload_legacy_document(
    client: httpx.Client,
    api_base: str,
    token: str,
    *,
    base_id: str,
    path: Path,
) -> tuple[str, str]:
    with path.open("rb") as handle:
        response = client.post(
            f"{api_base}/kb/documents/upload",
            headers={"Authorization": f"Bearer {token}"},
            data={"base_id": base_id, "category": "smoke-eval"},
            files=[("files", (path.name, handle, "text/plain"))],
        )
    response.raise_for_status()
    item = list(response.json()["items"])[0]
    return str(item["document_id"]), str(item["job_id"])


def wait_ingest_job(client: httpx.Client, api_base: str, token: str, job_id: str, *, timeout_seconds: int = 240) -> None:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        response = client.get(
            f"{api_base}/kb/ingest-jobs/{job_id}",
            headers={"Authorization": f"Bearer {token}"},
        )
        response.raise_for_status()
        payload = response.json()
        status_value = str(payload.get("status") or "")
        if status_value == "done":
            return
        if status_value in {"failed", "dead_letter"}:
            raise RuntimeError(f"ingest job failed: {job_id} status={status_value}")
        time.sleep(2.0)
    raise RuntimeError(f"ingest job did not complete before timeout: {job_id}")


def write_runtime_suite(policy_corpus_id: str, travel_corpus_id: str) -> Path:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    runtime_suite_path = REPORT_DIR / "agent_smoke_suite.runtime.json"
    runtime_suite = {
        "jobs": [
            {
                "name": "grounded_single",
                "eval_file": str((FIXTURE_DIR / "agent_smoke_grounded.json").resolve()),
                "scope_mode": "single",
                "corpus_ids": [policy_corpus_id],
                "document_ids": [],
                "execution_mode": "grounded",
            },
            {
                "name": "agent_multi",
                "eval_file": str((FIXTURE_DIR / "agent_smoke_agent.json").resolve()),
                "scope_mode": "multi",
                "corpus_ids": [policy_corpus_id, travel_corpus_id],
                "document_ids": [],
                "execution_mode": "agent",
            },
            {
                "name": "strict_refusal",
                "eval_file": str((FIXTURE_DIR / "agent_smoke_refusal.json").resolve()),
                "scope_mode": "single",
                "corpus_ids": [policy_corpus_id],
                "document_ids": [],
                "execution_mode": "grounded",
            },
        ]
    }
    runtime_suite_path.write_text(json.dumps(runtime_suite, ensure_ascii=False, indent=2), encoding="utf-8")
    return runtime_suite_path


def run_eval_suite(base_url: str, email: str, password: str, config_path: Path) -> None:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            sys.executable,
            str(EVAL_SUITE_SCRIPT),
            "--base-url",
            base_url.rstrip("/"),
            "--email",
            email,
            "--password",
            password,
            "--config",
            str(config_path),
            "--output",
            str(REPORT_DIR / "agent_smoke_report.json"),
            "--summary-output",
            str(REPORT_DIR / "agent_smoke_report.md"),
        ],
        check=True,
        cwd=str(REPO_ROOT),
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Run smoke upload + agent evaluation against the local project.")
    parser.add_argument("--base-url", default="http://localhost:8080/api/v1")
    parser.add_argument("--email", default="")
    parser.add_argument("--password", default="")
    parser.add_argument("--skip-upload", action="store_true")
    args = parser.parse_args()

    env_values = load_env_file()
    base_url = args.base_url.rstrip("/")
    email = args.email or env_values.get("ADMIN_EMAIL", "admin@local")
    password = args.password or env_values.get("ADMIN_PASSWORD", "")
    if not password:
        raise RuntimeError("ADMIN_PASSWORD is missing. Set it in .env or pass --password.")

    token = login(base_url, email, password)
    client = httpx.Client(timeout=60.0)
    api_base = base_url

    policy_corpus_id = env_values.get("SMOKE_POLICY_CORPUS_ID", "").strip()
    travel_corpus_id = env_values.get("SMOKE_TRAVEL_CORPUS_ID", "").strip()

    if not args.skip_upload or not policy_corpus_id or not travel_corpus_id:
        policy_base_id = create_base(client, api_base, token, "Smoke Policy Base", "Local smoke fixture for expense policy.")
        travel_base_id = create_base(client, api_base, token, "Smoke Travel Base", "Local smoke fixture for travel policy.")
        policy_document_id, policy_job_id = upload_legacy_document(
            client,
            api_base,
            token,
            base_id=policy_base_id,
            path=FIXTURE_DIR / "agent_smoke_policy.txt",
        )
        travel_document_id, travel_job_id = upload_legacy_document(
            client,
            api_base,
            token,
            base_id=travel_base_id,
            path=FIXTURE_DIR / "agent_smoke_travel.txt",
        )
        wait_ingest_job(client, api_base, token, policy_job_id)
        wait_ingest_job(client, api_base, token, travel_job_id)
        policy_corpus_id = f"kb:{policy_base_id}"
        travel_corpus_id = f"kb:{travel_base_id}"
        os.environ["SMOKE_POLICY_CORPUS_ID"] = policy_corpus_id
        os.environ["SMOKE_TRAVEL_CORPUS_ID"] = travel_corpus_id
        print(
            json.dumps(
                {
                    "policy_base_id": policy_base_id,
                    "travel_base_id": travel_base_id,
                    "policy_document_id": policy_document_id,
                    "travel_document_id": travel_document_id,
                },
                ensure_ascii=False,
            )
        )

    runtime_suite_path = write_runtime_suite(policy_corpus_id, travel_corpus_id)
    run_eval_suite(base_url, email, password, runtime_suite_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
