from __future__ import annotations

import asyncio
import importlib
import sys
from pathlib import Path
from types import SimpleNamespace

import httpx
from fastapi.testclient import TestClient
from langchain_core.documents import Document
from pydantic import ValidationError

from shared import auth as auth_module
from shared import embeddings as embeddings_module
from shared.embeddings import EmbeddingSettings, clear_query_embedding_cache, embed_query_text
from shared.idempotency import build_request_hash, normalize_idempotency_key
from shared.qdrant_store import qdrant_point_id
from shared.stack_init import _load_migration_files, _migration_checksum, _select_pending_migrations

REPO_ROOT = Path(__file__).resolve().parents[1]
GATEWAY_SRC = REPO_ROOT / "apps/services/api-gateway/src"
KB_SRC = REPO_ROOT / "apps/services/knowledge-base/src"


def test_select_pending_migrations_returns_only_unapplied(tmp_path: Path) -> None:
    migration_a = tmp_path / "001_init.sql"
    migration_b = tmp_path / "002_extra.sql"
    migration_a.write_text("CREATE TABLE a(id INT);\n", encoding="utf-8")
    migration_b.write_text("CREATE TABLE b(id INT);\n", encoding="utf-8")

    files = _load_migration_files(tmp_path)
    applied = {files[0].version: files[0].checksum}

    pending = _select_pending_migrations(files, applied)
    assert [item.version for item in pending] == ["002_extra.sql"]


def test_select_pending_migrations_rejects_checksum_mismatch(tmp_path: Path) -> None:
    migration = tmp_path / "001_init.sql"
    migration.write_text("CREATE TABLE a(id INT);\n", encoding="utf-8")

    files = _load_migration_files(tmp_path)
    mismatched = {"001_init.sql": _migration_checksum("CREATE TABLE broken(id INT);\n")}

    try:
        _select_pending_migrations(files, mismatched)
    except RuntimeError as exc:
        assert "checksum mismatch" in str(exc)
    else:
        raise AssertionError("expected checksum mismatch to raise RuntimeError")


def test_query_embedding_cache_reuses_previous_result(monkeypatch) -> None:
    clear_query_embedding_cache()
    calls = {"count": 0}

    def fake_embed_texts(texts: list[str], *, settings=None):
        calls["count"] += 1
        return [[0.25, 0.75]]

    monkeypatch.setattr(embeddings_module, "embed_texts", fake_embed_texts)
    settings = EmbeddingSettings(
        provider="local",
        api_url="",
        api_key="",
        model="local-projection-512",
        timeout_seconds=60.0,
        batch_size=64,
        local_backend="projection",
    )

    first = embed_query_text("expense approval flow", settings=settings)
    second = embed_query_text("expense approval flow", settings=settings)

    assert first == [0.25, 0.75]
    assert second == [0.25, 0.75]
    assert calls["count"] == 1


def test_gateway_to_json_preserves_empty_list() -> None:
    gateway_db = _load_gateway_module("app.db")

    assert gateway_db.to_json([]) == "[]"
    assert gateway_db.to_json(None) == "{}"


def test_message_feedback_request_normalizes_fields() -> None:
    gateway_schemas = _load_gateway_module("app.gateway_schemas")

    payload = gateway_schemas.MessageFeedbackRequest(verdict=" Down ", reason_code="Low Confidence", notes="  needs citations  ")

    assert payload.verdict == "down"
    assert payload.reason_code == "low_confidence"
    assert payload.notes == "needs citations"


def _prioritize_sys_path(path: Path) -> None:
    target = str(path)
    try:
        sys.path.remove(target)
    except ValueError:
        pass
    sys.path.insert(0, target)


def _load_gateway_main(monkeypatch):
    _prioritize_sys_path(GATEWAY_SRC)

    for name in ("app.main", "app.ai_client", "app.db", "app.gateway_chat_routes", "app.gateway_chat_service", "app.gateway_workflows", "app"):
        sys.modules.pop(name, None)

    module = importlib.import_module("app.main")
    return importlib.reload(module)


def _load_gateway_module(module_name: str):
    _prioritize_sys_path(GATEWAY_SRC)

    for name in (
        module_name,
        "app.main",
        "app.gateway_agent",
        "app.gateway_answering",
        "app.gateway_chat_routes",
        "app.gateway_chat_service",
        "app.gateway_workflows",
        "app.gateway_scope",
        "app.ai_client",
        "app.db",
        "app",
    ):
        sys.modules.pop(name, None)

    module = importlib.import_module(module_name)
    return importlib.reload(module)


def _load_kb_module(module_name: str):
    _prioritize_sys_path(KB_SRC)

    for name in (
        module_name,
        "app.main",
        "app.kb_query_helpers",
        "app.retrieve",
        "app.runtime",
        "app.db",
        "app.query",
        "app.worker",
        "app.vector_store",
        "app",
    ):
        sys.modules.pop(name, None)

    module = importlib.import_module(module_name)
    return importlib.reload(module)


def _auth_headers(user: auth_module.AuthUser) -> dict[str, str]:
    return {"Authorization": f"Bearer {auth_module.create_access_token(user)}"}


def test_resolve_scope_snapshot_persists_documents_by_corpus(monkeypatch) -> None:
    gateway_main = _load_gateway_main(monkeypatch)
    user = auth_module.AuthUser(user_id="u-1", email="member@local", role="member")

    async def fake_fetch_corpora(current_user, *, include_counts: bool):
        assert current_user == user
        assert include_counts is False
        return [
            {"corpus_id": "kb:base-1"},
            {"corpus_id": "kb:base-2"},
        ]

    async def fake_fetch_corpus_documents(client, *, user, corpus_id):
        assert user.user_id == "u-1"
        if corpus_id == "kb:base-1":
            return [{"document_id": "doc-a", "corpus_id": corpus_id}]
        return [{"document_id": "doc-b", "corpus_id": corpus_id}]

    monkeypatch.setattr(gateway_main, "_fetch_corpora", fake_fetch_corpora)
    monkeypatch.setattr(gateway_main, "_fetch_corpus_documents", fake_fetch_corpus_documents)

    payload = gateway_main.ChatScopePayload(
        mode="multi",
        corpus_ids=["kb:base-1", "kb:base-2"],
        document_ids=["doc-b", "doc-a"],
        allow_common_knowledge=True,
    )
    snapshot = asyncio.run(gateway_main._resolve_scope_snapshot(user, payload))

    assert snapshot["document_ids"] == ["doc-b", "doc-a"]
    assert snapshot["documents_by_corpus"] == {
        "kb:base-1": ["doc-a"],
        "kb:base-2": ["doc-b"],
    }
    assert snapshot["allow_common_knowledge"] is True


def test_retrieve_scope_evidence_uses_cached_document_scope(monkeypatch) -> None:
    gateway_main = _load_gateway_main(monkeypatch)
    user = auth_module.AuthUser(user_id="u-1", email="member@local", role="member")
    fetch_calls = {"count": 0}

    async def fail_if_fetch_documents(*args, **kwargs):
        fetch_calls["count"] += 1
        raise AssertionError("document lookup should be skipped when documents_by_corpus is cached")

    async def fake_request_service_json(client, method, url, *, headers, json_body=None):
        return {
            "items": [
                {
                    "corpus_id": f"kb:{json_body['base_id']}",
                    "document_id": json_body["document_ids"][0] if json_body["document_ids"] else "",
                    "evidence_path": {"final_score": 0.91},
                }
            ],
            "retrieval": {"retrieval_ms": 8.5, "original_query": "expense approval flow"},
            "trace_id": "kb-trace-1",
        }

    monkeypatch.setattr(gateway_main, "_fetch_corpus_documents", fail_if_fetch_documents)
    monkeypatch.setattr(gateway_main, "_request_service_json", fake_request_service_json)

    scope_snapshot = {
        "mode": "multi",
        "corpus_ids": ["kb:base-1", "kb:base-2"],
        "document_ids": ["doc-a", "doc-b"],
        "documents_by_corpus": {
            "kb:base-1": ["doc-a"],
            "kb:base-2": ["doc-b"],
        },
        "allow_common_knowledge": False,
    }

    evidence, contextualized_question, retrieval_meta = asyncio.run(
        gateway_main._retrieve_scope_evidence(
            user=user,
            scope_snapshot=scope_snapshot,
            question="What is the expense approval flow?",
            history=[],
        )
    )

    assert fetch_calls["count"] == 0
    assert contextualized_question == "What is the expense approval flow?"
    assert len(evidence) == 2
    assert retrieval_meta["aggregate"]["document_scope_cache_hit"] is True


def test_retrieve_scope_evidence_tolerates_partial_service_failure(monkeypatch) -> None:
    gateway_main = _load_gateway_main(monkeypatch)
    user = auth_module.AuthUser(user_id="u-1", email="member@local", role="member")

    async def fake_request_service_json(client, method, url, *, headers, json_body=None):
        if json_body["base_id"] == "base-2":
            raise gateway_main.HTTPException(
                status_code=502,
                detail={"detail": "kb retrieve unavailable", "code": "upstream_unavailable"},
            )
        return {
            "items": [
                {
                    "corpus_id": "kb:base-1",
                    "document_id": "doc-a",
                    "evidence_path": {"final_score": 0.88},
                }
            ],
            "retrieval": {"retrieval_ms": 6.0, "original_query": "expense approval flow"},
            "trace_id": "kb-trace-ok",
        }

    monkeypatch.setattr(gateway_main, "_request_service_json", fake_request_service_json)

    scope_snapshot = {
        "mode": "multi",
        "corpus_ids": ["kb:base-1", "kb:base-2"],
        "document_ids": ["doc-a", "doc-b"],
        "documents_by_corpus": {
            "kb:base-1": ["doc-a"],
            "kb:base-2": ["doc-b"],
        },
        "allow_common_knowledge": False,
    }

    evidence, _, retrieval_meta = asyncio.run(
        gateway_main._retrieve_scope_evidence(
            user=user,
            scope_snapshot=scope_snapshot,
            question="What is the expense approval flow?",
            history=[],
        )
    )

    assert len(evidence) == 1
    assert retrieval_meta["aggregate"]["partial_failure"] is True
    assert retrieval_meta["aggregate"]["failed_service_count"] == 1
    assert retrieval_meta["services"][1]["status"] == "failed"


def test_classify_evidence_returns_common_knowledge_without_evidence_when_allowed() -> None:
    gateway_answering = _load_gateway_module("app.gateway_answering")

    answer_mode, evidence_status, grounding_score, refusal_reason = gateway_answering.classify_evidence(
        [],
        allow_common_knowledge=True,
    )

    assert answer_mode == "common_knowledge"
    assert evidence_status == "ungrounded"
    assert grounding_score == 0.0
    assert refusal_reason == ""


def test_classify_evidence_prefers_common_knowledge_over_weak_grounding_when_allowed() -> None:
    gateway_answering = _load_gateway_module("app.gateway_answering")

    answer_mode, evidence_status, grounding_score, refusal_reason = gateway_answering.classify_evidence(
        [{"evidence_path": {"final_score": 0.015}}],
        allow_common_knowledge=True,
    )

    assert answer_mode == "common_knowledge"
    assert evidence_status == "ungrounded"
    assert grounding_score == 0.0
    assert refusal_reason == ""


def test_classify_evidence_refuses_without_evidence_in_strict_mode() -> None:
    gateway_answering = _load_gateway_module("app.gateway_answering")

    answer_mode, evidence_status, grounding_score, refusal_reason = gateway_answering.classify_evidence(
        [],
        allow_common_knowledge=False,
    )

    assert answer_mode == "refusal"
    assert evidence_status == "insufficient"
    assert grounding_score == 0.0
    assert refusal_reason == "insufficient_evidence"


def test_generate_grounded_answer_uses_general_llm_path_for_common_knowledge(monkeypatch) -> None:
    gateway_answering = _load_gateway_module("app.gateway_answering")
    captured: dict[str, object] = {}

    class _Settings:
        configured = True
        system_prompt = "custom system prompt"
        default_max_tokens = 900
        common_knowledge_model = "mock-common-model"
        common_knowledge_max_tokens = 256
        common_knowledge_history_messages = 1
        common_knowledge_history_chars = 24

    async def fake_create_llm_completion(*, settings, prompt, inputs, prompt_key=None, prompt_version=None, model, temperature, max_tokens):
        captured["settings"] = settings
        captured["prompt"] = prompt
        captured["inputs"] = inputs
        captured["prompt_key"] = prompt_key
        captured["prompt_version"] = prompt_version
        captured["model"] = model
        captured["temperature"] = temperature
        captured["max_tokens"] = max_tokens
        return {
            "answer": "The sun releases energy through nuclear fusion.",
            "provider": "mock-provider",
            "model": "mock-model",
            "usage": {"prompt_tokens": 10, "completion_tokens": 20},
            "llm_trace": {"llm_call_id": "llm-1", "prompt_key": "chat_common_knowledge", "prompt_version": "2026-03-10"},
        }

    monkeypatch.setattr(gateway_answering, "load_llm_settings", lambda: _Settings())
    monkeypatch.setattr(gateway_answering, "create_llm_completion", fake_create_llm_completion)

    result = asyncio.run(
        gateway_answering.generate_grounded_answer(
            question="Why does the sun shine?",
            history=[
                {"role": "user", "content": "outdated history should be removed"},
                {"role": "assistant", "content": "This assistant reply is intentionally longer than the history truncation limit."},
            ],
            evidence=[],
            answer_mode="common_knowledge",
        )
    )

    prompt = captured["prompt"]
    inputs = captured["inputs"]
    messages = prompt.format_messages(**inputs)
    rendered = [str(getattr(item, "content", "")) for item in messages]
    assert any("Why does the sun shine?" in item for item in rendered)
    assert not any("outdated history" in item for item in rendered)
    assert any("This assistant reply is" in item for item in rendered)
    assert not any("history truncation limit" in item for item in rendered)
    assert captured["model"] == "mock-common-model"
    assert captured["prompt_key"] == "chat_common_knowledge"
    assert captured["prompt_version"] == "2026-03-10"
    assert captured["temperature"] == 0.4
    assert captured["max_tokens"] == 256
    assert result["provider"] == "mock-provider"
    assert result["model"] == "mock-model"
    assert gateway_answering.COMMON_KNOWLEDGE_DISCLAIMER in result["answer"]
    assert "nuclear fusion" in result["answer"]
    assert result["llm_trace"]["prompt_key"] == "chat_common_knowledge"


def test_generate_grounded_answer_short_ambiguous_common_knowledge_skips_llm(monkeypatch) -> None:
    gateway_answering = _load_gateway_module("app.gateway_answering")

    class _Settings:
        configured = True
        system_prompt = ""
        model = "mock-model"
        common_knowledge_model = ""
        default_max_tokens = 900
        common_knowledge_max_tokens = 256
        common_knowledge_history_messages = 1
        common_knowledge_history_chars = 24

    async def fail_create_llm_completion(**kwargs):
        raise AssertionError("LLM should be skipped for low-signal common knowledge prompts")

    monkeypatch.setattr(gateway_answering, "load_llm_settings", lambda: _Settings())
    monkeypatch.setattr(gateway_answering, "create_llm_completion", fail_create_llm_completion)

    result = asyncio.run(
        gateway_answering.generate_grounded_answer(
            question="1",
            history=[],
            evidence=[],
            answer_mode="common_knowledge",
        )
    )

    assert result["provider"] == ""
    assert result["model"] == ""
    assert result["usage"] == {}
    assert result["llm_trace"] == {}
    assert "信息不足" in result["answer"]


def test_generate_grounded_answer_retries_with_fallback_route(monkeypatch) -> None:
    gateway_answering = _load_gateway_module("app.gateway_answering")
    attempts: list[tuple[str, str]] = []

    class _Settings:
        configured = True
        provider = "openai-compatible"
        base_url = "https://primary.example.test/v1"
        api_key = "secret"
        model = "default-model"
        system_prompt = "custom system prompt"
        default_temperature = 0.7
        default_max_tokens = 900
        common_knowledge_model = ""
        common_knowledge_max_tokens = 256
        common_knowledge_history_messages = 1
        common_knowledge_history_chars = 24
        timeout_seconds = 30.0
        extra_body = {}
        model_routing = {
            "grounded": {
                "model": "primary-grounded-model",
                "fallback_route_key": "grounded_backup",
                "temperature": 0.2,
                "max_tokens": 800,
            },
            "grounded_backup": {
                "model": "backup-grounded-model",
                "base_url": "https://backup.example.test/v1",
                "temperature": 0.2,
                "max_tokens": 800,
            },
        }

    async def fake_create_llm_completion(*, settings, prompt, inputs, prompt_key=None, prompt_version=None, model, temperature, max_tokens):
        attempts.append((settings.base_url, model))
        if model == "primary-grounded-model":
            raise gateway_answering.HTTPException(status_code=502, detail="primary unavailable")
        return {
            "answer": "Expense approvals require owner sign-off. [1]",
            "provider": "mock-provider",
            "model": model,
            "usage": {"prompt_tokens": 10, "completion_tokens": 20},
            "llm_trace": {"llm_call_id": "llm-2", "prompt_key": "chat_grounded_answer", "prompt_version": "2026-03-10"},
        }

    monkeypatch.setattr(gateway_answering, "load_llm_settings", lambda: _Settings())
    monkeypatch.setattr(gateway_answering, "create_llm_completion", fake_create_llm_completion)

    result = asyncio.run(
        gateway_answering.generate_grounded_answer(
            question="What approvals are needed for expense reimbursement?",
            history=[],
            evidence=[
                {
                    "document_title": "Expense policy",
                    "section_title": "Approval",
                    "quote": "Department owner approval is required before reimbursement.",
                    "raw_text": "Department owner approval is required before reimbursement.",
                    "evidence_path": {"final_score": 0.82},
                }
            ],
            answer_mode="grounded",
        )
    )

    assert attempts == [
        ("https://primary.example.test/v1", "primary-grounded-model"),
        ("https://backup.example.test/v1", "backup-grounded-model"),
    ]
    assert result["model"] == "backup-grounded-model"
    assert result["llm_trace"]["route_key"] == "grounded_backup"
    assert result["llm_trace"]["route_attempts"] == ["grounded", "grounded_backup"]
    assert result["llm_trace"]["fallback_used"] is True


def test_create_llm_completion_stream_yields_live_deltas(monkeypatch) -> None:
    ai_client = _load_gateway_module("app.ai_client")
    captured: dict[str, object] = {}

    class _FakeStreamResponse:
        status_code = 200
        headers = {"content-type": "text/event-stream"}

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def aiter_lines(self):
            yield 'data: {"model":"stream-model","choices":[{"delta":{"content":"Hello"},"finish_reason":""}]}'
            yield 'data: {"choices":[{"delta":{"content":" world"},"finish_reason":"stop"}],"usage":{"prompt_tokens":5,"completion_tokens":2}}'
            yield 'data: [DONE]'

        async def aread(self):
            return b""

    class _FakeAsyncClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        def stream(self, method, url, headers=None, json=None):
            captured["method"] = method
            captured["url"] = url
            captured["json"] = json
            return _FakeStreamResponse()

    monkeypatch.setattr(ai_client.httpx, "AsyncClient", _FakeAsyncClient)

    settings = ai_client.LLMSettings(
        enabled=True,
        provider="mock-provider",
        base_url="https://example.invalid/v1",
        api_key="secret",
        model="default-model",
        common_knowledge_model="",
        timeout_seconds=30.0,
        default_temperature=0.7,
        default_max_tokens=512,
        common_knowledge_max_tokens=256,
        common_knowledge_history_messages=4,
        common_knowledge_history_chars=400,
        system_prompt="",
        extra_body={},
    )
    snapshots: list[str] = []

    result = asyncio.run(
        ai_client.create_llm_completion_stream(
            settings=settings,
            messages=[{"role": "user", "content": "Say hello"}],
            model="stream-model",
            temperature=0.3,
            max_tokens=128,
            on_text_delta=lambda _delta, answer_text: snapshots.append(answer_text),
        )
    )

    assert snapshots == ["Hello", "Hello world"]
    assert captured["method"] == "POST"
    assert isinstance(captured["json"], dict)
    assert captured["json"]["stream"] is True
    assert captured["json"]["model"] == "stream-model"
    assert result["answer"] == "Hello world"
    assert result["model"] == "stream-model"
    assert result["usage"] == {"prompt_tokens": 5, "completion_tokens": 2}


def test_default_scope_disables_common_knowledge_fallback() -> None:
    gateway_scope = _load_gateway_module("app.gateway_scope")

    scope = gateway_scope.default_scope()

    assert scope["allow_common_knowledge"] is False
    assert scope["execution_mode"] == "grounded"


def test_prepare_chat_message_uses_agent_execution_mode(monkeypatch) -> None:
    gateway_chat_service = _load_gateway_module("app.gateway_chat_service")
    user = auth_module.AuthUser(user_id="u-1", email="member@local", role="member")
    captured: dict[str, object] = {}

    async def fake_run_agent_search(**kwargs):
        captured.update(kwargs)
        return (
            [{"unit_id": "chunk-1", "evidence_path": {"final_score": 0.87}}],
            "expense approval flow",
            {"aggregate": {"selected_candidates": 1, "execution_mode": "agent"}},
        )

    async def fail_retrieve_scope_evidence(**kwargs):
        raise AssertionError("grounded retriever should be skipped in agent mode")

    async def fake_resolve_scope_snapshot(current_user, scope_payload):
        assert current_user == user
        return {
            "mode": "single",
            "corpus_ids": ["kb:base-1"],
            "document_ids": [],
            "documents_by_corpus": {},
            "allow_common_knowledge": False,
        }

    monkeypatch.setattr(gateway_chat_service, "run_agent_search", fake_run_agent_search)

    prepared = asyncio.run(
        gateway_chat_service.prepare_chat_message(
            session_id="session-1",
            payload=SimpleNamespace(question="What is the expense approval flow?", scope=None, execution_mode=None),
            user=user,
            load_session_fn=lambda sid, actor: {"id": sid, "scope_json": {"execution_mode": "agent"}},
            default_scope_fn=lambda: {"mode": "all", "execution_mode": "grounded"},
            resolve_scope_snapshot_fn=fake_resolve_scope_snapshot,
            recent_history_messages_fn=lambda sid, actor, limit=8: [],
            retrieve_scope_evidence_fn=fail_retrieve_scope_evidence,
            fetch_corpus_documents_fn=lambda *args, **kwargs: [],
        )
    )

    assert prepared["execution_mode"] == "agent"
    assert prepared["scope_snapshot"]["execution_mode"] == "agent"
    assert prepared["contextualized_question"] == "expense approval flow"
    assert prepared["retrieval_meta"]["aggregate"]["execution_mode"] == "agent"
    assert captured["scope_snapshot"]["execution_mode"] == "agent"


def test_handle_chat_message_persists_workflow_run(monkeypatch) -> None:
    gateway_chat_service = _load_gateway_module("app.gateway_chat_service")
    user = auth_module.AuthUser(user_id="u-1", email="member@local", role="member")
    workflow_updates: list[dict[str, object]] = []

    async def fake_prepare_chat_message(**kwargs):
        return {
            "session_id": "session-1",
            "payload": SimpleNamespace(question="What is the expense approval flow?"),
            "trace_id": "gateway-trace-1",
            "scope_snapshot": {"mode": "single", "execution_mode": "agent"},
            "execution_mode": "agent",
            "history": [],
            "evidence": [{"unit_id": "chunk-1"}],
            "contextualized_question": "expense approval flow",
            "retrieval_meta": {
                "aggregate": {"selected_candidates": 1, "partial_failure": False},
                "agent": {"tool_calls": [{"tool": "search_scope", "result_count": 1}]},
            },
            "answer_mode": "grounded",
            "evidence_status": "grounded",
            "grounding_score": 0.91,
            "refusal_reason": "",
            "safety": {"risk_level": "low", "reason_codes": []},
            "timing": {"total_started": 0.0, "scope_ms": 1.0, "retrieval_ms": 2.0},
        }

    async def fake_generate_grounded_answer(**kwargs):
        return {"answer": "Use [1]", "provider": "mock", "model": "mock-model", "usage": {"prompt_tokens": 10}}

    def fake_build_chat_response_payload(**kwargs):
        return {
            "answer": "Use [1]",
            "answer_mode": "grounded",
            "strategy_used": "agent_grounded_qa",
            "citations": [{"unit_id": "chunk-1"}],
            "provider": "mock",
            "model": "mock-model",
            "usage": {"prompt_tokens": 10},
            "llm_trace": {"llm_call_id": "llm-1", "prompt_key": "chat_grounded_answer", "prompt_version": "2026-03-10"},
            "latency": {"total_ms": 12.0},
            "cost": {"estimated_cost": 0.01},
        }

    def fake_finalize_chat_message(**kwargs):
        response_payload = dict(kwargs["response_payload"])
        response_payload["message"] = {"id": "message-1", "content": "Use [1]"}
        return response_payload

    def fake_start_workflow_run_fn(**kwargs):
        return {"id": "run-1", "status": "running", "stage": "retrieval_completed"}

    def fake_update_workflow_run_fn(**kwargs):
        workflow_updates.append(dict(kwargs))
        state = dict(kwargs["workflow_state"])
        return {
            "id": kwargs["run_id"],
            "status": kwargs["status"],
            "stage": state.get("stage", ""),
            "message_id": kwargs.get("message_id", ""),
            "workflow_state": state,
            "workflow_events": list(kwargs.get("workflow_events") or []),
            "tool_calls": list(kwargs.get("tool_calls") or []),
        }

    monkeypatch.setattr(gateway_chat_service, "prepare_chat_message", fake_prepare_chat_message)
    monkeypatch.setattr(gateway_chat_service, "generate_grounded_answer", fake_generate_grounded_answer)
    monkeypatch.setattr(gateway_chat_service, "build_chat_response_payload", fake_build_chat_response_payload)
    monkeypatch.setattr(gateway_chat_service, "finalize_chat_message", fake_finalize_chat_message)

    result = asyncio.run(
        gateway_chat_service.handle_chat_message(
            session_id="session-1",
            payload=SimpleNamespace(question="What is the expense approval flow?"),
            request=SimpleNamespace(),
            user=user,
            load_session_fn=lambda *args, **kwargs: {},
            default_scope_fn=lambda: {"mode": "all"},
            resolve_scope_snapshot_fn=lambda *args, **kwargs: {},
            recent_history_messages_fn=lambda *args, **kwargs: [],
            retrieve_scope_evidence_fn=lambda *args, **kwargs: None,
            fetch_corpus_documents_fn=lambda *args, **kwargs: [],
            persist_chat_turn_fn=lambda *args, **kwargs: {},
            start_workflow_run_fn=fake_start_workflow_run_fn,
            update_workflow_run_fn=fake_update_workflow_run_fn,
        )
    )

    assert result["workflow_run"]["status"] == "completed"
    assert result["workflow_run"]["message_id"] == "message-1"
    assert workflow_updates[0]["status"] == "running"
    assert workflow_updates[0]["workflow_state"]["stage"] == "generation_completed"
    assert workflow_updates[0]["workflow_state"]["response"]["llm_trace"]["prompt_key"] == "chat_grounded_answer"
    assert workflow_updates[1]["status"] == "completed"
    assert workflow_updates[1]["message_id"] == "message-1"
    assert workflow_updates[1]["workflow_events"][-1]["stage"] == "persisted"
    assert workflow_updates[1]["tool_calls"] == [{"tool": "search_scope", "result_count": 1}]


def test_handle_chat_message_reuses_generation_checkpoint_for_persistence_resume(monkeypatch) -> None:
    gateway_chat_service = _load_gateway_module("app.gateway_chat_service")
    user = auth_module.AuthUser(user_id="u-1", email="member@local", role="member")
    started_runs: list[dict[str, object]] = []
    workflow_updates: list[dict[str, object]] = []
    build_payload_calls: list[dict[str, object]] = []

    async def fake_prepare_chat_message(**kwargs):
        return {
            "session_id": "session-1",
            "payload": SimpleNamespace(question="What is the expense approval flow?"),
            "trace_id": "gateway-trace-2",
            "scope_snapshot": {"mode": "single", "execution_mode": "agent"},
            "execution_mode": "agent",
            "history": [],
            "evidence": [{"unit_id": "chunk-1"}],
            "contextualized_question": "expense approval flow",
            "retrieval_meta": {
                "aggregate": {"selected_candidates": 1, "partial_failure": False},
                "agent": {"tool_calls": [{"tool": "search_scope", "result_count": 1}]},
            },
            "answer_mode": "grounded",
            "evidence_status": "grounded",
            "grounding_score": 0.91,
            "refusal_reason": "",
            "safety": {"risk_level": "low", "reason_codes": []},
            "timing": {"total_started": 0.0, "scope_ms": 1.0, "retrieval_ms": 0.0, "resume_ms": 0.1},
            "resume": {
                "resumed": True,
                "source_run_id": "run-0",
                "source_stage": "failed",
                "resume_target": "persist_message",
                "reused_retrieval": True,
                "reused_generation": True,
            },
            "generation_checkpoint": {
                "answer_payload": {
                    "answer": "Use [1]",
                    "provider": "mock",
                    "model": "mock-model",
                    "usage": {"prompt_tokens": 10},
                    "llm_trace": {"llm_call_id": "llm-2", "prompt_key": "chat_grounded_answer", "prompt_version": "2026-03-10"},
                },
                "generation_ms": 18.5,
            },
        }

    async def fail_generate_grounded_answer(**kwargs):
        raise AssertionError("generation should be reused from checkpoint")

    def fake_build_chat_response_payload(**kwargs):
        build_payload_calls.append(dict(kwargs))
        return {
            "answer": kwargs["answer_payload"]["answer"],
            "answer_mode": "grounded",
            "strategy_used": "agent_grounded_qa",
            "citations": [{"unit_id": "chunk-1"}],
            "provider": kwargs["answer_payload"]["provider"],
            "model": kwargs["answer_payload"]["model"],
            "usage": dict(kwargs["answer_payload"]["usage"]),
            "llm_trace": dict(kwargs["answer_payload"]["llm_trace"]),
            "latency": {"total_ms": 12.0, "generation_ms": kwargs["generation_ms"]},
            "cost": {"estimated_cost": 0.01},
        }

    def fake_finalize_chat_message(**kwargs):
        response_payload = dict(kwargs["response_payload"])
        response_payload["message"] = {"id": "message-2", "content": response_payload["answer"]}
        return response_payload

    def fake_start_workflow_run_fn(**kwargs):
        started_runs.append(dict(kwargs))
        return {"id": "run-2", "status": "running", "stage": "persistence_resumed"}

    def fake_update_workflow_run_fn(**kwargs):
        workflow_updates.append(dict(kwargs))
        state = dict(kwargs["workflow_state"])
        return {
            "id": kwargs["run_id"],
            "status": kwargs["status"],
            "stage": state.get("stage", ""),
            "message_id": kwargs.get("message_id", ""),
            "workflow_state": state,
            "workflow_events": list(kwargs.get("workflow_events") or []),
            "tool_calls": list(kwargs.get("tool_calls") or []),
        }

    monkeypatch.setattr(gateway_chat_service, "prepare_chat_message", fake_prepare_chat_message)
    monkeypatch.setattr(gateway_chat_service, "generate_grounded_answer", fail_generate_grounded_answer)
    monkeypatch.setattr(gateway_chat_service, "build_chat_response_payload", fake_build_chat_response_payload)
    monkeypatch.setattr(gateway_chat_service, "finalize_chat_message", fake_finalize_chat_message)

    result = asyncio.run(
        gateway_chat_service.handle_chat_message(
            session_id="session-1",
            payload=SimpleNamespace(question="What is the expense approval flow?"),
            request=SimpleNamespace(),
            user=user,
            load_session_fn=lambda *args, **kwargs: {},
            default_scope_fn=lambda: {"mode": "all"},
            resolve_scope_snapshot_fn=lambda *args, **kwargs: {},
            recent_history_messages_fn=lambda *args, **kwargs: [],
            retrieve_scope_evidence_fn=lambda *args, **kwargs: None,
            fetch_corpus_documents_fn=lambda *args, **kwargs: [],
            persist_chat_turn_fn=lambda *args, **kwargs: {},
            start_workflow_run_fn=fake_start_workflow_run_fn,
            update_workflow_run_fn=fake_update_workflow_run_fn,
        )
    )

    assert result["workflow_run"]["status"] == "completed"
    assert result["workflow_run"]["message_id"] == "message-2"
    assert started_runs[0]["workflow_state"]["stage"] == "persistence_resumed"
    assert started_runs[0]["workflow_state"]["resume_target"] == "persist_message"
    assert started_runs[0]["workflow_state"]["resume_checkpoint"]["generation_checkpoint"]["generation_ms"] == 18.5
    assert build_payload_calls[0]["generation_ms"] == 18.5
    assert len(workflow_updates) == 1
    assert workflow_updates[0]["status"] == "completed"
    assert workflow_updates[0]["workflow_state"]["stage"] == "persisted"


def test_retry_chat_workflow_run_uses_idempotency_and_audit(monkeypatch) -> None:
    gateway_chat_routes = _load_gateway_module("app.gateway_chat_routes")
    user = auth_module.AuthUser(user_id="u-1", email="member@local", role="member")
    captured: dict[str, object] = {}
    audit_events: list[dict[str, object]] = []
    released_tickets: list[object] = []

    async def fake_handle_chat_message(**kwargs):
        return {
            "message": {"id": "message-2"},
            "workflow_run": {"id": "run-2"},
            "answer": "Use [1]",
        }

    monkeypatch.setattr(gateway_chat_routes, "require_permission", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        gateway_chat_routes,
        "load_workflow_run_for_user",
        lambda run_id, current_user: {
            "id": run_id,
            "session_id": "session-1",
            "status": "failed",
            "question": "What is the expense approval flow?",
            "execution_mode": "agent",
            "scope_snapshot": {
                "mode": "single",
                "corpus_ids": ["kb:base-1"],
                "document_ids": [],
                "allow_common_knowledge": False,
            },
        },
    )
    monkeypatch.setattr(
        gateway_chat_routes,
        "load_session_for_user",
        lambda session_id, current_user, default_scope_fn=None: {"id": session_id, "scope_json": {"execution_mode": "agent"}},
    )
    monkeypatch.setattr(
        gateway_chat_routes,
        "begin_gateway_idempotency",
        lambda request, current_user, request_scope, payload: (
            captured.update({"request_scope": request_scope, "payload": payload}) or SimpleNamespace(
                key="retry-key",
                request_scope=request_scope,
                request_hash="hash",
                replay_payload=None,
                enabled=True,
            )
        ),
    )
    monkeypatch.setattr(
        gateway_chat_routes,
        "handle_chat_message",
        fake_handle_chat_message,
    )
    monkeypatch.setattr(
        gateway_chat_routes,
        "complete_gateway_idempotency",
        lambda state, current_user, response_payload, resource_id="": captured.update(
            {"completed_resource_id": resource_id, "completed_payload": response_payload}
        ),
    )
    monkeypatch.setattr(
        gateway_chat_routes,
        "fail_gateway_idempotency",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("retry should not mark idempotency as failed")),
    )
    monkeypatch.setattr(
        gateway_chat_routes,
        "write_gateway_audit_event",
        lambda **kwargs: audit_events.append(dict(kwargs)),
    )
    monkeypatch.setattr(
        gateway_chat_routes.CHAT_INFLIGHT_LIMITER,
        "acquire",
        lambda **kwargs: SimpleNamespace(allowed=True, ticket="ticket-1", scope=""),
    )
    monkeypatch.setattr(
        gateway_chat_routes.CHAT_INFLIGHT_LIMITER,
        "release",
        lambda ticket: released_tickets.append(ticket),
    )

    result = asyncio.run(
        gateway_chat_routes.retry_chat_workflow_run(
            "run-1",
            gateway_chat_routes.RetryWorkflowRunRequest(reuse_scope=True),
            SimpleNamespace(headers={}),
            user,
        )
    )

    assert result["retried_from_run_id"] == "run-1"
    assert captured["request_scope"] == "chat.workflow_run.retry"
    assert captured["payload"] == {
        "run_id": "run-1",
        "session_id": "session-1",
        "question": "What is the expense approval flow?",
        "execution_mode": "agent",
        "reuse_scope": True,
        "scope": {
            "mode": "single",
            "corpus_ids": ["kb:base-1"],
            "document_ids": [],
            "allow_common_knowledge": False,
        },
    }
    assert captured["completed_resource_id"] == "message-2"
    assert released_tickets == ["ticket-1"]
    assert audit_events[-1]["action"] == "chat.workflow_run.retry"
    assert audit_events[-1]["outcome"] == "success"
    assert audit_events[-1]["details"]["new_workflow_run_id"] == "run-2"


def test_build_chat_workflow_state_includes_agent_events() -> None:
    gateway_chat_service = _load_gateway_module("app.gateway_chat_service")

    prepared = {
        "execution_mode": "agent",
        "answer_mode": "grounded",
        "payload": SimpleNamespace(question="What is the expense approval flow?"),
        "contextualized_question": "expense approval flow",
        "scope_snapshot": {"mode": "single"},
        "evidence": [{"unit_id": "chunk-1"}],
        "retrieval_meta": {
            "aggregate": {"selected_candidates": 1, "partial_failure": False},
            "agent": {"events": [{"type": "tool_request", "tool": "search_scope"}]},
        },
        "safety": {"risk_level": "low"},
        "timing": {"retrieval_ms": 4.0},
    }

    state = gateway_chat_service.build_chat_workflow_state(prepared=prepared, stage="retrieval_completed")

    assert state["agent_events"] == [{"type": "tool_request", "tool": "search_scope"}]


def test_handle_chat_message_marks_workflow_failed_on_generation_error(monkeypatch) -> None:
    gateway_chat_service = _load_gateway_module("app.gateway_chat_service")
    user = auth_module.AuthUser(user_id="u-1", email="member@local", role="member")
    workflow_updates: list[dict[str, object]] = []

    async def fake_prepare_chat_message(**kwargs):
        return {
            "session_id": "session-1",
            "payload": SimpleNamespace(question="What is the expense approval flow?"),
            "trace_id": "gateway-trace-1",
            "scope_snapshot": {"mode": "single", "execution_mode": "agent"},
            "execution_mode": "agent",
            "history": [],
            "evidence": [],
            "contextualized_question": "expense approval flow",
            "retrieval_meta": {"aggregate": {"selected_candidates": 0, "partial_failure": False}, "agent": {"tool_calls": []}},
            "answer_mode": "refusal",
            "evidence_status": "insufficient",
            "grounding_score": 0.0,
            "refusal_reason": "insufficient_evidence",
            "safety": {"risk_level": "low", "reason_codes": []},
            "timing": {"total_started": 0.0, "scope_ms": 1.0, "retrieval_ms": 2.0},
        }

    async def fail_generate_grounded_answer(**kwargs):
        raise RuntimeError("llm failed")

    def fake_start_workflow_run_fn(**kwargs):
        return {"id": "run-1", "status": "running", "stage": "retrieval_completed"}

    def fake_update_workflow_run_fn(**kwargs):
        workflow_updates.append(dict(kwargs))
        return {
            "id": kwargs["run_id"],
            "status": kwargs["status"],
            "stage": kwargs["workflow_state"].get("stage", ""),
            "workflow_events": list(kwargs.get("workflow_events") or []),
        }

    monkeypatch.setattr(gateway_chat_service, "prepare_chat_message", fake_prepare_chat_message)
    monkeypatch.setattr(gateway_chat_service, "generate_grounded_answer", fail_generate_grounded_answer)

    try:
        asyncio.run(
            gateway_chat_service.handle_chat_message(
                session_id="session-1",
                payload=SimpleNamespace(question="What is the expense approval flow?"),
                request=SimpleNamespace(),
                user=user,
                load_session_fn=lambda *args, **kwargs: {},
                default_scope_fn=lambda: {"mode": "all"},
                resolve_scope_snapshot_fn=lambda *args, **kwargs: {},
                recent_history_messages_fn=lambda *args, **kwargs: [],
                retrieve_scope_evidence_fn=lambda *args, **kwargs: None,
                fetch_corpus_documents_fn=lambda *args, **kwargs: [],
                persist_chat_turn_fn=lambda *args, **kwargs: {},
                start_workflow_run_fn=fake_start_workflow_run_fn,
                update_workflow_run_fn=fake_update_workflow_run_fn,
            )
        )
    except RuntimeError as exc:
        assert str(exc) == "llm failed"
    else:
        raise AssertionError("expected generation failure to propagate")

    assert workflow_updates[-1]["status"] == "failed"
    assert workflow_updates[-1]["workflow_state"]["stage"] == "failed"
    assert workflow_updates[-1]["workflow_state"]["error"]["type"] == "RuntimeError"
    assert workflow_updates[-1]["workflow_events"][-1]["status"] == "failed"


def test_run_agent_search_degrades_to_grounded_when_tool_calling_fails(monkeypatch) -> None:
    gateway_agent = _load_gateway_module("app.gateway_agent")
    user = auth_module.AuthUser(user_id="u-1", email="member@local", role="member")

    class _Settings:
        configured = True
        model = "mock-model"
        default_max_tokens = 512

    class _BrokenModel:
        def bind_tools(self, tools):
            return self

        async def ainvoke(self, messages):
            raise RuntimeError("quota exhausted")

    async def fake_retrieve_scope_evidence_fn(**kwargs):
        return (
            [{"unit_id": "chunk-1", "evidence_path": {"final_score": 0.91}}],
            "expense approval flow",
            {"aggregate": {"selected_candidates": 1}, "services": []},
        )

    monkeypatch.setattr(gateway_agent, "load_llm_settings", lambda: _Settings())
    monkeypatch.setattr(gateway_agent, "build_chat_model", lambda **kwargs: _BrokenModel())

    evidence, contextualized_question, retrieval_meta = asyncio.run(
        gateway_agent.run_agent_search(
            user=user,
            scope_snapshot={
                "mode": "single",
                "corpus_ids": ["kb:base-1"],
                "document_ids": [],
                "documents_by_corpus": {},
                "allow_common_knowledge": False,
                "execution_mode": "agent",
            },
            question="What is the expense approval flow?",
            history=[],
            retrieve_scope_evidence_fn=fake_retrieve_scope_evidence_fn,
            fetch_corpus_documents_fn=lambda *args, **kwargs: [],
            kb_service_url="http://kb-service:8200",
        )
    )

    assert len(evidence) == 1
    assert contextualized_question == "expense approval flow"
    assert retrieval_meta["aggregate"]["execution_mode"] == "agent"
    assert retrieval_meta["aggregate"]["agent_fallback"] is True
    assert retrieval_meta["aggregate"]["tool_budget"] == 3
    assert retrieval_meta["agent"]["fallback"] is True
    assert retrieval_meta["agent"]["tool_budget"]["max_tool_calls"] == 3
    assert retrieval_meta["agent"]["allowed_tools"] == ["search_scope", "list_scope_documents", "search_corpus"]
    assert retrieval_meta["agent"]["tool_calls_used"] == 0


def test_run_agent_search_records_agent_events(monkeypatch) -> None:
    gateway_agent = _load_gateway_module("app.gateway_agent")
    user = auth_module.AuthUser(user_id="u-1", email="member@local", role="member")

    class _Settings:
        configured = True
        model = "mock-model"
        default_max_tokens = 512

    class _FakeModel:
        def bind_tools(self, tools):
            self._tools = tools
            return self

        async def ainvoke(self, messages):
            if not any(isinstance(item, gateway_agent.ToolMessage) for item in messages):
                return gateway_agent.AIMessage(
                    content="Searching scope first.",
                    tool_calls=[
                        {
                            "id": "call-1",
                            "name": "search_scope",
                            "args": {"search_question": "expense approval flow", "limit": 3},
                        }
                    ],
                )
            return gateway_agent.AIMessage(content="Enough evidence found.")

    async def fake_retrieve_scope_evidence_fn(**kwargs):
        return (
            [{"unit_id": "chunk-1", "document_title": "Policy", "section_title": "Approval", "quote": "Need finance approval", "evidence_path": {"final_score": 0.91}}],
            "expense approval flow",
            {"aggregate": {"selected_candidates": 1}, "services": []},
        )

    monkeypatch.setattr(gateway_agent, "load_llm_settings", lambda: _Settings())
    monkeypatch.setattr(gateway_agent, "build_chat_model", lambda **kwargs: _FakeModel())

    evidence, _, retrieval_meta = asyncio.run(
        gateway_agent.run_agent_search(
            user=user,
            scope_snapshot={
                "mode": "single",
                "corpus_ids": ["kb:base-1"],
                "document_ids": [],
                "documents_by_corpus": {},
                "allow_common_knowledge": False,
                "execution_mode": "agent",
            },
            question="What is the expense approval flow?",
            history=[],
            retrieve_scope_evidence_fn=fake_retrieve_scope_evidence_fn,
            fetch_corpus_documents_fn=lambda *args, **kwargs: [],
            kb_service_url="http://kb-service:8200",
        )
    )

    assert len(evidence) == 1
    agent_events = retrieval_meta["agent"]["events"]
    assert agent_events[0]["type"] == "agent_started"
    assert any(event["type"] == "tool_request" and event["tool"] == "search_scope" for event in agent_events)
    assert any(event["type"] == "tool_result" and event["tool"] == "search_scope" for event in agent_events)
    assert retrieval_meta["aggregate"]["tool_calls_used"] == 1
    assert retrieval_meta["agent"]["allowed_tools"] == ["search_scope", "list_scope_documents", "search_corpus"]
    assert retrieval_meta["agent"]["tool_calls_used"] == 1


def test_common_knowledge_answers_are_prefixed_with_disclaimer() -> None:
    gateway_answering = _load_gateway_module("app.gateway_answering")

    answer = gateway_answering.ensure_common_knowledge_disclaimer("The sun releases energy through nuclear fusion.")

    assert gateway_answering.COMMON_KNOWLEDGE_DISCLAIMER in answer
    assert "nuclear fusion" in answer


def test_search_vector_evidence_degrades_when_qdrant_query_fails(monkeypatch) -> None:
    kb_vector_store = _load_kb_module("app.vector_store")

    def fail_build_vector_retriever(*, base_id, document_ids, limit):
        raise RuntimeError("qdrant unavailable")

    monkeypatch.setattr(kb_vector_store, "build_vector_retriever", fail_build_vector_retriever)

    evidence, degraded_signals, warnings = kb_vector_store.search_vector_evidence(
        base_id="base-1",
        question="expense approval flow",
        document_ids=["doc-1"],
        limit=4,
    )

    assert evidence == []
    assert degraded_signals == ["vector"]
    assert warnings == ["vector retrieval disabled because qdrant query execution failed"]


def test_gateway_readiness_checks_degrade_llm_without_failing(monkeypatch) -> None:
    gateway_main = _load_gateway_main(monkeypatch)

    class _Cursor:
        def execute(self, query):
            return None

        def fetchone(self):
            return {"ok": 1}

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    class _Connection:
        def cursor(self):
            return _Cursor()

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    class _FakeAsyncClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def get(self, url):
            class _Response:
                status_code = 200

            return _Response()

    monkeypatch.setattr(gateway_main.gateway_db, "connect", lambda: _Connection())
    monkeypatch.setattr(gateway_main.httpx, "AsyncClient", _FakeAsyncClient)
    monkeypatch.setenv("LLM_API_KEY", "")
    monkeypatch.setenv("LLM_BASE_URL", "")
    monkeypatch.setenv("LLM_MODEL", "")

    checks = asyncio.run(gateway_main._gateway_readiness_checks())

    assert checks["database"]["status"] == "ok"
    assert checks["kb_service"]["status"] == "ok"
    assert checks["llm"]["status"] == "fallback"


def test_kb_readiness_checks_require_storage(monkeypatch) -> None:
    kb_main = _load_kb_module("app.main")

    class _Cursor:
        def execute(self, query):
            return None

        def fetchone(self):
            return {"ok": 1}

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    class _Connection:
        def cursor(self):
            return _Cursor()

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr(kb_main.db, "connect", lambda: _Connection())
    monkeypatch.setattr(kb_main.storage, "check_bucket_access", lambda: (_ for _ in ()).throw(RuntimeError("bucket missing")))
    monkeypatch.setitem(kb_main._kb_readiness_checks.__globals__, "check_vector_store", lambda: {"collection": "kb-evidence"})

    checks = kb_main._kb_readiness_checks()

    assert checks["database"]["status"] == "ok"
    assert checks["object_storage"]["status"] == "failed"
    assert checks["vector_store"]["status"] == "ok"


def test_auth_configuration_allows_default_credentials_in_local_runtime(monkeypatch) -> None:
    monkeypatch.delenv("APP_ENV", raising=False)
    monkeypatch.delenv("ENVIRONMENT", raising=False)
    monkeypatch.setenv("JWT_SECRET", auth_module.DEFAULT_JWT_SECRET)
    monkeypatch.setenv("ADMIN_PASSWORD", auth_module.DEFAULT_LOCAL_PASSWORD)
    monkeypatch.setenv("MEMBER_PASSWORD", auth_module.DEFAULT_LOCAL_PASSWORD)

    warnings = auth_module.ensure_auth_configuration_ready()

    assert len(warnings) == 3


def test_auth_configuration_rejects_default_credentials_outside_local(monkeypatch) -> None:
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("JWT_SECRET", auth_module.DEFAULT_JWT_SECRET)
    monkeypatch.setenv("ADMIN_PASSWORD", auth_module.DEFAULT_LOCAL_PASSWORD)
    monkeypatch.setenv("MEMBER_PASSWORD", auth_module.DEFAULT_LOCAL_PASSWORD)

    try:
        auth_module.ensure_auth_configuration_ready()
    except RuntimeError as exc:
        assert "insecure auth configuration" in str(exc)
    else:
        raise AssertionError("expected insecure non-local auth configuration to raise RuntimeError")


def test_upsert_chat_message_feedback_snapshots_llm_metadata(monkeypatch) -> None:
    gateway_sessions = _load_gateway_module("app.gateway_sessions")
    user = auth_module.AuthUser(user_id="user-1", email="member@local", role="member")
    message_row = {
        "id": "msg-1",
        "session_id": "session-1",
        "user_id": "user-1",
        "role": "assistant",
        "answer_mode": "grounded",
        "provider": "openai-compatible",
        "model": "gpt-4.1-mini",
        "scope_snapshot_json": {"execution_mode": "agent"},
        "usage_json": {
            "_meta": {
                "trace_id": "gateway-trace-1",
                "cost": {"estimated_cost": 0.0123, "currency": "USD"},
                "llm_trace": {
                    "prompt_key": "chat_grounded_answer",
                    "prompt_version": "2026-03-10",
                    "route_key": "grounded",
                    "model_resolved": "gpt-4.1-mini",
                },
            }
        },
    }

    class _Cursor:
        def __init__(self) -> None:
            self._row = None

        def execute(self, query, params=None):
            if "FROM chat_messages" in query:
                self._row = message_row
            elif "INSERT INTO chat_message_feedback" in query:
                self._row = {
                    "id": "feedback-1",
                    "session_id": params[1],
                    "message_id": params[2],
                    "user_id": params[3],
                    "verdict": params[4],
                    "reason_code": params[5],
                    "notes": params[6],
                    "trace_id": params[7],
                    "prompt_key": params[8],
                    "prompt_version": params[9],
                    "route_key": params[10],
                    "model": params[11],
                    "provider": params[12],
                    "execution_mode": params[13],
                    "answer_mode": params[14],
                    "cost_json": {"estimated_cost": 0.0123, "currency": "USD"},
                    "llm_trace_json": {"prompt_key": "chat_grounded_answer", "prompt_version": "2026-03-10", "route_key": "grounded"},
                    "created_at": None,
                    "updated_at": None,
                }
            return None

        def fetchone(self):
            return self._row

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    class _Connection:
        def cursor(self):
            return _Cursor()

        def commit(self):
            return None

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr(gateway_sessions.gateway_db, "connect", lambda: _Connection())

    feedback = gateway_sessions.upsert_chat_message_feedback(
        session_id="session-1",
        message_id="msg-1",
        user=user,
        verdict="down",
        reason_code="low_confidence",
        notes="needs citations",
    )

    assert feedback["verdict"] == "down"
    assert feedback["reason_code"] == "low_confidence"
    assert feedback["trace_id"] == "gateway-trace-1"
    assert feedback["prompt_key"] == "chat_grounded_answer"
    assert feedback["prompt_version"] == "2026-03-10"
    assert feedback["route_key"] == "grounded"
    assert feedback["model"] == "gpt-4.1-mini"
    assert feedback["provider"] == "openai-compatible"
    assert feedback["execution_mode"] == "agent"
    assert feedback["cost"]["estimated_cost"] == 0.0123


def test_list_session_messages_attaches_feedback_payload(monkeypatch) -> None:
    gateway_sessions = _load_gateway_module("app.gateway_sessions")
    user = auth_module.AuthUser(user_id="user-1", email="member@local", role="member")
    message_row = {
        "id": "msg-1",
        "session_id": "session-1",
        "role": "assistant",
        "question": "",
        "answer": "approved",
        "answer_mode": "grounded",
        "evidence_status": "grounded",
        "grounding_score": 0.9,
        "refusal_reason": "",
        "citations_json": [],
        "evidence_path_json": [],
        "scope_snapshot_json": {"execution_mode": "grounded"},
        "provider": "openai-compatible",
        "model": "gpt-4.1-mini",
        "usage_json": {"_meta": {"trace_id": "gateway-trace-1", "cost": {}, "llm_trace": {}}},
        "created_at": None,
    }
    feedback_row = {
        "id": "feedback-1",
        "session_id": "session-1",
        "message_id": "msg-1",
        "verdict": "up",
        "reason_code": "helpful",
        "notes": "",
        "trace_id": "gateway-trace-1",
        "prompt_key": "chat_grounded_answer",
        "prompt_version": "2026-03-10",
        "route_key": "grounded",
        "model": "gpt-4.1-mini",
        "provider": "openai-compatible",
        "execution_mode": "grounded",
        "answer_mode": "grounded",
        "cost_json": {},
        "llm_trace_json": {},
        "created_at": None,
        "updated_at": None,
    }

    class _Cursor:
        def __init__(self) -> None:
            self._rows = []

        def execute(self, query, params=None):
            if "FROM chat_messages" in query:
                self._rows = [message_row]
            elif "FROM chat_message_feedback" in query:
                self._rows = [feedback_row]
            return None

        def fetchall(self):
            return list(self._rows)

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    class _Connection:
        def cursor(self):
            return _Cursor()

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr(gateway_sessions.gateway_db, "connect", lambda: _Connection())

    messages = gateway_sessions.list_session_messages("session-1", user, load_session_fn=lambda *_args, **_kwargs: None)

    assert len(messages) == 1
    assert messages[0]["id"] == "msg-1"
    assert messages[0]["feedback"]["verdict"] == "up"


def test_kb_analytics_dashboard_payload_aggregates_ingest_health(monkeypatch) -> None:
    kb_analytics = _load_kb_module("app.kb_analytics_routes")
    user = auth_module.AuthUser(
        user_id="user-1",
        email="member@local",
        role="kb_editor",
        permissions=auth_module.permissions_for_role("kb_editor"),
    )

    class _Cursor:
        def __init__(self) -> None:
            self._row = None
            self._rows = []

        def execute(self, query, params=None):
            if "FROM kb_bases" in query:
                self._row = {"total_count": 2}
                self._rows = []
            elif "COUNT(*) AS uploaded_count" in query:
                self._row = {"uploaded_count": 6}
                self._rows = []
            elif "COUNT(*) AS ready_count" in query:
                self._row = {"ready_count": 4}
                self._rows = []
            elif "AVG(EXTRACT(EPOCH FROM (ready_at - created_at))" in query:
                self._row = {
                    "sample_count": 4,
                    "avg_ms": 82000.0,
                    "p50_ms": 78000.0,
                    "p95_ms": 110000.0,
                    "max_ms": 120000.0,
                }
                self._rows = []
            elif "COUNT(*) AS total_documents" in query:
                self._row = {
                    "total_documents": 8,
                    "ready_documents": 4,
                    "queryable_documents": 5,
                    "failed_documents": 1,
                    "unfinished_documents": 4,
                    "stalled_documents": 1,
                    "dead_letter_documents": 1,
                    "in_progress_documents": 2,
                }
                self._rows = []
            elif "COALESCE(NULLIF(enhancement_status, ''), 'none')" in query:
                self._rows = [
                    {"key": "chunk_vectors_ready", "total_count": 4},
                    {"key": "visual_ready", "total_count": 2},
                    {"key": "failed", "total_count": 1},
                ]
                self._row = None
            elif "COALESCE(NULLIF(status, ''), 'missing')" in query:
                self._rows = [
                    {"key": "done", "total_count": 4},
                    {"key": "processing", "total_count": 2},
                    {"key": "dead_letter", "total_count": 1},
                ]
                self._row = None
            elif "COALESCE(NULLIF(status, ''), 'unknown')" in query:
                self._rows = [
                    {"key": "ready", "total_count": 4},
                    {"key": "enhancing", "total_count": 2},
                    {"key": "failed", "total_count": 1},
                ]
                self._row = None
            else:
                raise AssertionError(f"unexpected query: {query}")

        def fetchone(self):
            return self._row

        def fetchall(self):
            return list(self._rows)

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    class _Connection:
        def cursor(self):
            return _Cursor()

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr(kb_analytics.db, "connect", lambda: _Connection())

    payload = kb_analytics._dashboard_payload(user, view="personal", days=14)

    assert payload["funnel"]["knowledge_bases_created"] == 2
    assert payload["funnel"]["documents_uploaded"] == 6
    assert payload["funnel"]["documents_ready"] == 4
    assert payload["ingest_health"]["summary"]["dead_letter_documents"] == 1
    assert payload["ingest_health"]["summary"]["stalled_documents"] == 1
    assert payload["ingest_health"]["upload_to_ready_latency_ms"]["p95_ms"] == 110000.0
    assert payload["ingest_health"]["document_status_distribution"][0]["key"] == "ready"


def test_gateway_qa_quality_stats_handles_empty_window(monkeypatch) -> None:
    gateway_analytics = _load_gateway_module("app.gateway_analytics_routes")
    user = auth_module.AuthUser(
        user_id="user-1",
        email="member@local",
        role="kb_editor",
        permissions=auth_module.permissions_for_role("kb_editor"),
    )

    class _Cursor:
        def __init__(self) -> None:
            self._row = None
            self._rows = []

        def execute(self, query, params=None):
            if "COUNT(*) AS assistant_answers" in query:
                self._row = {
                    "assistant_answers": 0,
                    "refusal_answers": 0,
                    "weak_grounded_answers": 0,
                    "grounded_answers": 0,
                    "selected_candidates_zero": 0,
                    "missing_citations": 0,
                    "missing_citations_non_refusal": 0,
                    "zero_hit_non_refusal": 0,
                    "grounding_score_lt_0_5": 0,
                    "partial_evidence": 0,
                    "low_quality_answers": 0,
                }
                self._rows = []
            elif "COALESCE(NULLIF(answer_mode, ''), 'unknown')" in query or "COALESCE(NULLIF(evidence_status, ''), 'unknown')" in query:
                self._rows = []
                self._row = None
            else:
                raise AssertionError(f"unexpected query: {query}")

        def fetchone(self):
            return self._row

        def fetchall(self):
            return list(self._rows)

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    class _Connection:
        def cursor(self):
            return _Cursor()

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr(gateway_analytics.gateway_db, "connect", lambda: _Connection())

    payload = gateway_analytics._qa_quality_stats(user, view="personal", days=14)

    assert payload["summary"]["assistant_answers"] == 0
    assert payload["zero_hit"]["selected_candidates_zero_rate"] == 0.0
    assert payload["low_quality"]["rate"] == 0.0
    assert payload["answer_mode_distribution"] == []
    assert payload["evidence_status_distribution"] == []


def test_gateway_dashboard_route_returns_extended_payload(monkeypatch) -> None:
    gateway_main = _load_gateway_main(monkeypatch)
    gateway_analytics = importlib.import_module("app.gateway_analytics_routes")
    user = auth_module.AuthUser(
        user_id="admin-1",
        email="admin@local",
        role="platform_admin",
        permissions=auth_module.permissions_for_role("platform_admin"),
    )

    monkeypatch.setattr(gateway_analytics, "_hot_terms", lambda *_args, **_kwargs: [{"term": "expense", "count": 3}])
    monkeypatch.setattr(gateway_analytics, "_zero_hit_stats", lambda *_args, **_kwargs: {"trend": [], "top_queries": []})
    monkeypatch.setattr(gateway_analytics, "_satisfaction_stats", lambda *_args, **_kwargs: {"trend": []})
    monkeypatch.setattr(
        gateway_analytics,
        "_usage_stats",
        lambda *_args, **_kwargs: {"currency": "USD", "summary": {"assistant_turns": 8, "prompt_tokens": 1200.0, "completion_tokens": 480.0, "estimated_cost": 0.52}, "trend": []},
    )
    monkeypatch.setattr(
        gateway_analytics,
        "_chat_funnel_stats",
        lambda *_args, **_kwargs: {
            "chat_sessions_with_questions": 5,
            "questions_asked": 11,
            "answer_outcomes": {"grounded": 7, "weak_grounded": 2, "refusal": 1, "other": 0},
            "feedback": {"up": 4, "down": 1, "flag": 0},
        },
    )
    monkeypatch.setattr(
        gateway_analytics,
        "_qa_quality_stats",
        lambda *_args, **_kwargs: {
            "summary": {"assistant_answers": 10, "grounded_answers": 7, "weak_grounded_answers": 2, "refusal_answers": 1},
            "answer_mode_distribution": [{"key": "grounded", "count": 7}],
            "evidence_status_distribution": [{"key": "grounded", "count": 7}],
            "zero_hit": {"selected_candidates_zero": 1, "selected_candidates_zero_rate": 0.1, "missing_citations": 2, "missing_citations_rate": 0.2},
            "low_quality": {"count": 2, "rate": 0.2, "score_threshold": 0.5, "reason_breakdown": [{"key": "partial_evidence", "count": 2}]},
        },
    )

    async def _fake_kb_dashboard_snapshot(current_user, *, view: str, days: int):
        assert current_user.user_id == "admin-1"
        assert view == "admin"
        assert days == 30
        return (
            {
                "funnel": {
                    "knowledge_bases_created": 2,
                    "documents_uploaded": 6,
                    "documents_ready": 4,
                },
                "ingest_health": {
                    "summary": {"total_documents": 8, "ready_documents": 4},
                    "document_status_distribution": [{"key": "ready", "count": 4}],
                    "latest_job_status_distribution": [{"key": "done", "count": 4}],
                    "enhancement_status_distribution": [{"key": "chunk_vectors_ready", "count": 4}],
                    "upload_to_ready_latency_ms": {"count": 4, "avg_ms": 82000.0, "p50_ms": 78000.0, "p95_ms": 110000.0, "max_ms": 120000.0, "unsupported": False},
                },
                "data_quality": {"unsupported_fields": [], "degraded_sections": []},
            },
            [],
        )

    monkeypatch.setattr(gateway_analytics, "_kb_dashboard_snapshot", _fake_kb_dashboard_snapshot)
    monkeypatch.setattr(gateway_analytics, "write_gateway_audit_event", lambda **_kwargs: None)

    client = TestClient(gateway_main.app)
    response = client.get("/api/v1/analytics/dashboard?view=admin&days=30", headers=_auth_headers(user))

    assert response.status_code == 200
    payload = response.json()
    assert payload["funnel"]["knowledge_bases_created"] == 2
    assert payload["funnel"]["questions_asked"] == 11
    assert payload["qa_quality"]["zero_hit"]["selected_candidates_zero"] == 1
    assert payload["ingest_health"]["summary"]["ready_documents"] == 4
    assert payload["data_quality"]["unsupported_fields"] == []


def test_gateway_dashboard_route_rejects_invalid_days(monkeypatch) -> None:
    gateway_main = _load_gateway_main(monkeypatch)
    user = auth_module.AuthUser(
        user_id="admin-1",
        email="admin@local",
        role="platform_admin",
        permissions=auth_module.permissions_for_role("platform_admin"),
    )

    client = TestClient(gateway_main.app)
    response = client.get("/api/v1/analytics/dashboard?days=0", headers=_auth_headers(user))

    assert response.status_code == 422
    payload = response.json()
    assert payload["code"] == "validation_error"


def test_gateway_dashboard_route_requires_chat_permission(monkeypatch) -> None:
    gateway_main = _load_gateway_main(monkeypatch)
    gateway_audit_support = importlib.import_module("app.gateway_audit_support")
    monkeypatch.setattr(gateway_audit_support, "write_gateway_audit_event", lambda **_kwargs: None)
    user = auth_module.AuthUser(
        user_id="audit-1",
        email="audit@local",
        role="audit_viewer",
        permissions=auth_module.permissions_for_role("audit_viewer"),
    )

    client = TestClient(gateway_main.app)
    response = client.get("/api/v1/analytics/dashboard", headers=_auth_headers(user))

    assert response.status_code == 403
    payload = response.json()
    assert payload["code"] == "permission_denied"


def test_kb_analytics_dashboard_route_requires_kb_read_permission(monkeypatch) -> None:
    kb_main = _load_kb_module("app.main")
    kb_api_support = importlib.import_module("app.kb_api_support")
    monkeypatch.setattr(kb_api_support, "audit_event", lambda **_kwargs: None)
    user = auth_module.AuthUser(
        user_id="audit-1",
        email="audit@local",
        role="audit_viewer",
        permissions=auth_module.permissions_for_role("audit_viewer"),
    )

    client = TestClient(kb_main.app)
    response = client.get("/api/v1/kb/analytics/dashboard", headers=_auth_headers(user))

    assert response.status_code == 403
    payload = response.json()
    assert payload["code"] == "permission_denied"


def test_auth_permissions_are_derived_from_role_aliases() -> None:
    admin_permissions = auth_module.permissions_for_role("admin")
    member_permissions = auth_module.permissions_for_role("member")

    assert "kb.manage" in admin_permissions
    assert "audit.read" in admin_permissions
    assert "kb.write" in member_permissions
    assert "chat.use" in member_permissions


def test_decode_access_token_backfills_permissions_for_legacy_role(monkeypatch) -> None:
    monkeypatch.setenv("JWT_SECRET", "test-secret")
    token = auth_module.jwt.encode(
        {
            "sub": "u-1",
            "email": "member@local",
            "role": "member",
            "iat": 100,
            "exp": 9999999999,
        },
        "test-secret",
        algorithm="HS256",
    )

    user = auth_module.decode_access_token(token)

    assert user.role == "kb_editor"
    assert "kb.write" in user.permissions
    assert "chat.use" in user.permissions


def test_merge_audit_event_lists_orders_by_created_at(monkeypatch) -> None:
    gateway_main = _load_gateway_main(monkeypatch)

    merged = gateway_main._merge_audit_event_lists(
        [
            {"id": "1", "created_at": "2026-03-09T10:00:00+00:00", "service": "gateway"},
            {"id": "2", "created_at": "2026-03-09T08:00:00+00:00", "service": "gateway"},
        ],
        [
            {"id": "3", "created_at": "2026-03-09T09:00:00+00:00", "service": "kb-service"},
        ],
        limit=2,
        offset=0,
    )

    assert [item["id"] for item in merged] == ["1", "3"]


def test_idempotency_hash_is_stable_for_equivalent_payloads() -> None:
    left = build_request_hash(
        "chat.message.send",
        {"question": "expense approval", "scope": {"mode": "single", "document_ids": ["a", "b"]}},
    )
    right = build_request_hash(
        "chat.message.send",
        {"scope": {"document_ids": ["a", "b"], "mode": "single"}, "question": "expense approval"},
    )

    assert left == right
    assert normalize_idempotency_key("  key-123 \n") == "key-123"


def test_qdrant_point_id_is_stable_uuid() -> None:
    left = qdrant_point_id(unit_type="section", unit_id="11111111-1111-1111-1111-111111111111")
    right = qdrant_point_id(unit_type="section", unit_id="11111111-1111-1111-1111-111111111111")
    other = qdrant_point_id(unit_type="chunk", unit_id="11111111-1111-1111-1111-111111111111")

    assert left == right
    assert other != left
    assert len(left) == 36


def test_worker_retry_delay_uses_bounded_backoff() -> None:
    kb_worker = _load_kb_module("app.worker")

    assert kb_worker._retry_delay_seconds(1) == 5
    assert kb_worker._retry_delay_seconds(2) == 15
    assert kb_worker._retry_delay_seconds(9) == 300


def test_create_upload_request_accepts_image_types() -> None:
    _prioritize_sys_path(KB_SRC)
    kb_schemas = importlib.import_module("app.kb_schemas")

    payload = kb_schemas.CreateUploadRequest(
        base_id="base-1",
        file_name="evidence.png",
        file_type=".PNG",
        size_bytes=12,
        category="images",
    )

    assert payload.file_type == "png"


def test_create_upload_request_rejects_unknown_type() -> None:
    _prioritize_sys_path(KB_SRC)
    kb_schemas = importlib.import_module("app.kb_schemas")

    try:
        kb_schemas.CreateUploadRequest(
            base_id="base-1",
            file_name="sheet.xlsx",
            file_type="xlsx",
            size_bytes=12,
            category="images",
        )
    except ValidationError as exc:
        assert "unsupported kb file type" in str(exc)
    else:
        raise AssertionError("expected invalid file type to raise ValidationError")


def test_extract_visual_assets_supports_standalone_png(tmp_path: Path) -> None:
    _prioritize_sys_path(KB_SRC)
    kb_vision = importlib.import_module("app.vision")
    image_path = tmp_path / "sample.png"
    from PIL import Image

    Image.new("RGB", (32, 16), color=(255, 255, 255)).save(image_path)

    assets = kb_vision.extract_visual_assets(image_path, "png", max_assets=8)

    assert len(assets) == 1
    assert assets[0].source_kind == "standalone"
    assert assets[0].page_number == 1
    assert assets[0].mime_type in {"image/png", "image/jpeg"}


def test_worker_merge_ingest_stats_combines_visual_counts() -> None:
    kb_worker = _load_kb_module("app.worker")

    merged = kb_worker._merge_ingest_stats(
        {"section_count": 2, "chunk_count": 3, "section_preview": ["a"]},
        {
            "visual_asset_count": 4,
            "visual_ocr_section_count": 1,
            "visual_ocr_chunk_count": 2,
            "visual_provider": "local-http",
            "section_preview": ["a", "b"],
            "visual_ms": 12.5,
        },
    )

    assert merged["section_count"] == 3
    assert merged["chunk_count"] == 5
    assert merged["visual_asset_count"] == 4
    assert merged["visual_provider"] == "local-http"


def test_retrieve_merge_documents_include_visual_metadata() -> None:
    kb_retrieve = _load_kb_module("app.retrieve")
    results: dict[str, object] = {}
    signal_lists: dict[str, list[str]] = {}

    kb_retrieve._merge_documents(
        results,
        signal_lists,
        [
            Document(
                page_content="approval amount limit",
                metadata={
                    "unit_id": "chunk-1",
                    "document_id": "doc-1",
                    "document_title": "Policy",
                    "section_title": "Page 3 screenshot 1",
                    "source_kind": "visual_ocr",
                    "page_number": 3,
                    "asset_id": "asset-1",
                    "thumbnail_url": "/api/v1/kb/visual-assets/asset-1/thumbnail",
                    "char_range": "0-20",
                    "quote": "approval amount limit",
                    "raw_text": "approval amount limit",
                    "base_id": "base-1",
                    "signal_scores": {"fts": 0.88},
                    "evidence_path": {"fts_rank": 1},
                },
            )
        ],
        "fts",
    )

    item = results["chunk-1"]
    assert item.evidence_kind == "visual_ocr"
    assert item.page_number == 3
    assert item.asset_id == "asset-1"
    assert item.thumbnail_url == "/api/v1/kb/visual-assets/asset-1/thumbnail"


def test_resolve_document_ids_defaults_to_current_active_effective_versions(monkeypatch) -> None:
    kb_retrieve = _load_kb_module("app.retrieve")
    executed_queries: list[str] = []

    class _Cursor:
        def __init__(self) -> None:
            self._rows = []

        def execute(self, query, params=None):
            executed_queries.append(query)
            self._rows = [{"id": "doc-current"}]

        def fetchall(self):
            return list(self._rows)

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    class _Connection:
        def cursor(self):
            return _Cursor()

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr(kb_retrieve.db, "connect", lambda: _Connection())

    resolved = kb_retrieve._resolve_document_ids(base_id="base-1", document_ids=[])

    assert resolved == ["doc-current"]
    assert len(executed_queries) == 1
    assert "version_status = 'active'" in executed_queries[0]
    assert "is_current_version = TRUE" in executed_queries[0]
    assert "effective_from IS NULL OR effective_from <= NOW()" in executed_queries[0]


def test_resolve_document_ids_keeps_explicit_version_selection(monkeypatch) -> None:
    kb_retrieve = _load_kb_module("app.retrieve")
    executed_queries: list[str] = []

    class _Cursor:
        def __init__(self) -> None:
            self._rows = []

        def execute(self, query, params=None):
            executed_queries.append(query)
            self._rows = [{"id": "doc-legacy"}]

        def fetchall(self):
            return list(self._rows)

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    class _Connection:
        def cursor(self):
            return _Cursor()

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr(kb_retrieve.db, "connect", lambda: _Connection())

    resolved = kb_retrieve._resolve_document_ids(base_id="base-1", document_ids=["doc-legacy"])

    assert resolved == ["doc-legacy"]
    assert len(executed_queries) == 1
    assert "id = ANY" in executed_queries[0]
    assert "version_status = 'active'" not in executed_queries[0]


def test_create_upload_request_normalizes_version_metadata() -> None:
    kb_schemas = _load_kb_module("app.kb_schemas")

    payload = kb_schemas.CreateUploadRequest(
        base_id="base-1",
        file_name="policy.pdf",
        file_type=".PDF",
        size_bytes=1024,
        category="policy",
        version_family_key=" expense-policy ",
        version_label=" 2026-Q1 ",
        version_number=3,
        version_status=" Active ",
        is_current_version=True,
        supersedes_document_id=" doc-old ",
    )

    assert payload.file_type == "pdf"
    assert payload.version_family_key == "expense-policy"
    assert payload.version_label == "2026-Q1"
    assert payload.version_status == "active"
    assert payload.supersedes_document_id == "doc-old"


def test_update_document_request_rejects_non_active_current_version() -> None:
    kb_schemas = _load_kb_module("app.kb_schemas")

    try:
        kb_schemas.UpdateDocumentRequest(version_status="archived", is_current_version=True)
    except ValidationError as exc:
        assert "current version must use active status" in str(exc)
    else:
        raise AssertionError("expected invalid current version status to raise ValidationError")


def test_build_version_diff_payload_summarizes_changes() -> None:
    kb_base_routes = _load_kb_module("app.kb_base_routes")

    source_chunks = [
        {"section_index": 0, "chunk_index": 0, "section_title": "Overview", "text_content": "line-a", "disabled": False},
        {"section_index": 1, "chunk_index": 0, "section_title": "Rules", "text_content": "old-rule", "disabled": False},
    ]
    target_chunks = [
        {"section_index": 0, "chunk_index": 0, "section_title": "Overview", "text_content": "line-a", "disabled": False},
        {"section_index": 1, "chunk_index": 0, "section_title": "Rules", "text_content": "new-rule", "disabled": False},
        {"section_index": 2, "chunk_index": 0, "section_title": "Appendix", "text_content": "extra", "disabled": False},
    ]

    payload = kb_base_routes._build_version_diff_payload(
        source_document={"id": "doc-v1", "version_label": "v1", "file_name": "policy-v1.pdf"},
        source_chunks=source_chunks,
        target_document={"id": "doc-v2", "version_label": "v2", "file_name": "policy-v2.pdf"},
        target_chunks=target_chunks,
    )

    assert payload["summary"]["added_chunks"] == 1
    assert payload["summary"]["removed_chunks"] == 0
    assert payload["summary"]["modified_chunks"] == 1
    assert "--- v1" in payload["diff_text"]
    assert "+++ v2" in payload["diff_text"]
    assert "new-rule" in payload["diff_text"]


def test_connector_scheduler_manager_runs_only_when_active() -> None:
    kb_scheduler = _load_kb_module("app.kb_connector_scheduler")
    active = {"value": False}
    calls: list[dict[str, object]] = []

    def has_active() -> bool:
        return bool(active["value"])

    def run_due_batch(*, limit: int, dry_run: bool, user) -> dict[str, object]:
        calls.append({"limit": limit, "dry_run": dry_run, "user_id": user.user_id})
        active["value"] = False
        return {"items": [], "count": 0}

    async def scenario() -> None:
        manager = kb_scheduler.ConnectorSchedulerManager(
            has_active_schedules=has_active,
            run_due_batch=run_due_batch,
            min_poll_seconds=5,
            max_batch_size=3,
        )
        manager.bind_loop(asyncio.get_running_loop())
        manager.reconcile()
        await asyncio.sleep(0.05)
        assert calls == []
        active["value"] = True
        manager.reconcile()
        await asyncio.sleep(0.1)
        assert len(calls) == 1
        assert calls[0]["limit"] == 3
        assert calls[0]["dry_run"] is False
        await manager.shutdown()

    asyncio.run(scenario())


def test_request_service_json_preserves_upstream_4xx() -> None:
    gateway_transport = _load_gateway_module("app.gateway_transport")

    class FakeClient:
        async def request(self, method, url, *, headers=None, json=None, params=None):
            return httpx.Response(
                404,
                json={"detail": "kb base not found", "code": "kb_base_not_found"},
                request=httpx.Request(method, url),
            )

    try:
        asyncio.run(
            gateway_transport.request_service_json(
                FakeClient(),
                "GET",
                "http://kb-service:8200/api/v1/kb/bases/base-1",
                headers={},
            )
        )
    except gateway_transport.HTTPException as exc:
        assert exc.status_code == 404
        assert exc.detail["detail"] == "kb base not found"
        assert exc.detail["code"] == "kb_base_not_found"
        assert exc.detail["upstream_status"] == 404
    else:
        raise AssertionError("expected upstream 404 to be preserved")


def test_request_service_json_wraps_upstream_5xx_as_502() -> None:
    gateway_transport = _load_gateway_module("app.gateway_transport")

    class FakeClient:
        async def request(self, method, url, *, headers=None, json=None, params=None):
            return httpx.Response(
                503,
                json={"detail": "kb analytics unavailable", "code": "kb_not_ready"},
                request=httpx.Request(method, url),
            )

    try:
        asyncio.run(
            gateway_transport.request_service_json(
                FakeClient(),
                "GET",
                "http://kb-service:8200/api/v1/kb/analytics/dashboard",
                headers={},
            )
        )
    except gateway_transport.HTTPException as exc:
        assert exc.status_code == 502
        assert exc.detail["detail"] == "kb analytics unavailable"
        assert exc.detail["code"] == "kb_not_ready"
        assert exc.detail["upstream_status"] == 503
    else:
        raise AssertionError("expected upstream 503 to be wrapped as 502")


