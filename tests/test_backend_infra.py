from __future__ import annotations

import asyncio
import importlib
import sys
from pathlib import Path
from types import SimpleNamespace

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


def _prioritize_sys_path(path: Path) -> None:
    target = str(path)
    try:
        sys.path.remove(target)
    except ValueError:
        pass
    sys.path.insert(0, target)


def _load_gateway_main(monkeypatch):
    _prioritize_sys_path(GATEWAY_SRC)

    for name in ("app.main", "app.ai_client", "app.db", "app"):
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

    async def fake_create_llm_completion(*, settings, prompt, inputs, model, temperature, max_tokens):
        captured["settings"] = settings
        captured["prompt"] = prompt
        captured["inputs"] = inputs
        captured["model"] = model
        captured["temperature"] = temperature
        captured["max_tokens"] = max_tokens
        return {
            "answer": "The sun releases energy through nuclear fusion.",
            "provider": "mock-provider",
            "model": "mock-model",
            "usage": {"prompt_tokens": 10, "completion_tokens": 20},
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
    assert captured["temperature"] == 0.4
    assert captured["max_tokens"] == 256
    assert result["provider"] == "mock-provider"
    assert result["model"] == "mock-model"
    assert gateway_answering.COMMON_KNOWLEDGE_DISCLAIMER in result["answer"]
    assert "nuclear fusion" in result["answer"]


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
    assert "信息不足" in result["answer"]


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
    assert retrieval_meta["agent"]["fallback"] is True


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


