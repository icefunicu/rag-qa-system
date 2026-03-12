from __future__ import annotations

import asyncio
import importlib
import sys
from pathlib import Path

from shared import auth as auth_module
from shared.retrieval import RetrievalResult, RetrievalStats


REPO_ROOT = Path(__file__).resolve().parents[1]
GATEWAY_SRC = REPO_ROOT / "apps/services/api-gateway/src"
KB_SRC = REPO_ROOT / "apps/services/knowledge-base/src"


def _prioritize_sys_path(path: Path) -> None:
    target = str(path)
    try:
        sys.path.remove(target)
    except ValueError:
        pass
    sys.path.insert(0, target)


def _load_gateway_module(module_name: str):
    _prioritize_sys_path(GATEWAY_SRC)
    for name in (
        module_name,
        "app.gateway_graph",
        "app.gateway_chat_service",
        "app.gateway_workflows",
        "app.gateway_answering",
        "app.gateway_runtime",
        "app.gateway_schemas",
        "app",
    ):
        sys.modules.pop(name, None)
    module = importlib.import_module(module_name)
    return importlib.reload(module)


def _load_kb_module(module_name: str):
    gateway_target = str(GATEWAY_SRC)
    try:
        sys.path.remove(gateway_target)
    except ValueError:
        pass
    _prioritize_sys_path(KB_SRC)
    for name in (module_name, "app.retrieve", "app", "app.runtime", "app.db"):
        sys.modules.pop(name, None)
    module = importlib.import_module(module_name)
    return importlib.reload(module)


def _graph_deps(gateway_graph):
    return gateway_graph.GatewayGraphDependencies(
        load_session_fn=lambda *args, **kwargs: {},
        default_scope_fn=lambda: {"mode": "all"},
        resolve_scope_snapshot_fn=lambda *args, **kwargs: {},
        recent_history_messages_fn=lambda *args, **kwargs: [],
        retrieve_scope_evidence_fn=lambda *args, **kwargs: None,
        fetch_corpus_documents_fn=lambda *args, **kwargs: [],
        persist_chat_turn_fn=lambda *args, **kwargs: {},
        session_cost_summary_fn=lambda *args, **kwargs: {"assistant_turns": 0, "estimated_cost_total": 0.0},
    )


def test_gateway_graph_run_completes_with_memory_checkpoint(monkeypatch) -> None:
    monkeypatch.setenv("GATEWAY_GRAPH_CHECKPOINTER", "memory")
    gateway_graph = _load_gateway_module("app.gateway_graph")
    user = auth_module.AuthUser(user_id="u-1", email="member@local", role="member")
    updates: list[dict[str, object]] = []

    async def fake_prepare_chat_message(**kwargs):
        return {
            "session_id": "session-1",
            "payload": kwargs["payload"],
            "trace_id": "gateway-trace-1",
            "scope_snapshot": {"mode": "single", "execution_mode": "agent"},
            "execution_mode": "agent",
            "history": [],
            "evidence": [{"unit_id": "chunk-1"}],
            "contextualized_question": "expense approval flow",
            "retrieval_meta": {"aggregate": {"selected_candidates": 1}, "agent": {"tool_calls": [{"tool": "search_scope"}]}},
            "answer_mode": "grounded",
            "evidence_status": "grounded",
            "grounding_score": 0.93,
            "refusal_reason": "",
            "safety": {"risk_level": "low", "reason_codes": []},
            "settings_prompt_append": "",
            "timing": {"total_started": 0.0, "scope_ms": 1.0, "retrieval_ms": 2.0},
        }

    async def fake_generate_grounded_answer(**kwargs):
        return {"answer": "Use [1]", "provider": "mock", "model": "mock-model", "usage": {"prompt_tokens": 8}, "llm_trace": {}}

    def fake_finalize_chat_message(**kwargs):
        payload = dict(kwargs["response_payload"])
        payload["message"] = {"id": "message-1", "content": payload["answer"]}
        return payload

    monkeypatch.setattr(gateway_graph, "prepare_chat_message", fake_prepare_chat_message)
    monkeypatch.setattr(gateway_graph, "generate_grounded_answer", fake_generate_grounded_answer)
    monkeypatch.setattr(gateway_graph, "finalize_chat_message", fake_finalize_chat_message)
    monkeypatch.setattr(
        gateway_graph,
        "create_workflow_run",
        lambda **kwargs: {"id": "run-1", "session_id": kwargs["session_id"], "status": "running"},
    )
    monkeypatch.setattr(
        gateway_graph,
        "update_workflow_run",
        lambda **kwargs: (updates.append(dict(kwargs)) or {"id": kwargs["run_id"], "session_id": "session-1", "status": kwargs["status"]}),
    )

    result = asyncio.run(
        gateway_graph.run_gateway_graph_turn(
            session_id="session-1",
            payload={"question": "What is the expense approval flow?", "scope": None, "execution_mode": "agent"},
            request_scope="chat.v2.run.create",
            user=user,
            request_path="/api/v2/chat/threads/session-1/runs",
            deps=_graph_deps(gateway_graph),
        )
    )

    assert result["status"] == "completed"
    assert result["run"]["status"] == "completed"
    assert result["message"]["id"] == "message-1"
    assert result["verification"]["status"] == "passed"
    assert updates[-1]["status"] == "completed"
    assert updates[-1]["tool_calls"] == [{"tool": "search_scope"}]


def test_gateway_graph_run_interrupts_and_resumes(monkeypatch) -> None:
    monkeypatch.setenv("GATEWAY_GRAPH_CHECKPOINTER", "memory")
    gateway_graph = _load_gateway_module("app.gateway_graph")
    user = auth_module.AuthUser(user_id="u-1", email="member@local", role="member")
    run_updates: list[dict[str, object]] = []
    interrupt_updates: list[dict[str, object]] = []

    async def fake_prepare_chat_message(**kwargs):
        question = kwargs["payload"].question
        if question == "Clarify expense approval flow":
            return {
                "session_id": "session-2",
                "payload": kwargs["payload"],
                "trace_id": "gateway-trace-2",
                "scope_snapshot": {"mode": "single", "execution_mode": "agent"},
                "execution_mode": "agent",
                "history": [],
                "evidence": [{"unit_id": "chunk-2"}],
                "contextualized_question": "Clarify expense approval flow",
                "retrieval_meta": {"aggregate": {"selected_candidates": 1}, "agent": {"tool_calls": [{"tool": "search_scope"}]}},
                "answer_mode": "grounded",
                "evidence_status": "grounded",
                "grounding_score": 0.88,
                "refusal_reason": "",
                "safety": {"risk_level": "low", "reason_codes": []},
                "settings_prompt_append": "",
                "timing": {"total_started": 0.0, "scope_ms": 1.0, "retrieval_ms": 2.0},
            }
        return {
            "session_id": "session-2",
            "payload": kwargs["payload"],
            "trace_id": "gateway-trace-2",
            "scope_snapshot": {"mode": "single", "execution_mode": "agent", "allow_common_knowledge": False},
            "execution_mode": "agent",
            "history": [],
            "evidence": [],
            "contextualized_question": "Need help",
            "retrieval_meta": {"aggregate": {"selected_candidates": 0}, "agent": {"tool_calls": []}},
            "answer_mode": "refusal",
            "evidence_status": "insufficient",
            "grounding_score": 0.0,
            "refusal_reason": "insufficient_evidence",
            "safety": {"risk_level": "low", "reason_codes": []},
            "settings_prompt_append": "",
            "timing": {"total_started": 0.0, "scope_ms": 1.0, "retrieval_ms": 2.0},
        }

    async def fake_generate_grounded_answer(**kwargs):
        return {"answer": "Use [1]", "provider": "mock", "model": "mock-model", "usage": {"prompt_tokens": 5}, "llm_trace": {}}

    def fake_finalize_chat_message(**kwargs):
        payload = dict(kwargs["response_payload"])
        payload["message"] = {"id": "message-2", "content": payload["answer"]}
        return payload

    monkeypatch.setattr(gateway_graph, "prepare_chat_message", fake_prepare_chat_message)
    monkeypatch.setattr(gateway_graph, "generate_grounded_answer", fake_generate_grounded_answer)
    monkeypatch.setattr(gateway_graph, "finalize_chat_message", fake_finalize_chat_message)
    monkeypatch.setattr(
        gateway_graph,
        "create_workflow_run",
        lambda **kwargs: {"id": "run-2", "session_id": kwargs["session_id"], "status": "running"},
    )
    monkeypatch.setattr(
        gateway_graph,
        "update_workflow_run",
        lambda **kwargs: (run_updates.append(dict(kwargs)) or {"id": kwargs["run_id"], "session_id": "session-2", "status": kwargs["status"], "interrupt_id": kwargs.get("interrupt_id", "")}),
    )
    monkeypatch.setattr(
        gateway_graph,
        "create_graph_interrupt",
        lambda **kwargs: {"id": "interrupt-1", "run_id": kwargs["run_id"], "session_id": kwargs["session_id"], "status": "pending", "payload": kwargs["payload"]},
    )
    monkeypatch.setattr(
        gateway_graph,
        "update_graph_interrupt",
        lambda interrupt_id, **kwargs: (interrupt_updates.append({"interrupt_id": interrupt_id, **kwargs}) or {"id": interrupt_id, "status": kwargs["status"]}),
    )
    monkeypatch.setattr(
        gateway_graph,
        "load_workflow_run_for_user",
        lambda run_id, current_user: {"id": run_id, "session_id": "session-2", "status": "interrupted", "interrupt_id": "interrupt-1"},
    )

    interrupted = asyncio.run(
        gateway_graph.run_gateway_graph_turn(
            session_id="session-2",
            payload={"question": "Need help", "scope": None, "execution_mode": "agent"},
            request_scope="chat.v2.run.create",
            user=user,
            request_path="/api/v2/chat/threads/session-2/runs",
            deps=_graph_deps(gateway_graph),
        )
    )

    assert interrupted["status"] == "interrupted"
    assert interrupted["interrupt"]["id"] == "interrupt-1"
    assert interrupted["run"]["status"] == "interrupted"

    resumed = asyncio.run(
        gateway_graph.resume_gateway_graph_turn(
            run_id="run-2",
            user=user,
            response_payload={"question": "Clarify expense approval flow"},
            deps=_graph_deps(gateway_graph),
            interrupt_id="interrupt-1",
        )
    )

    assert resumed["status"] == "completed"
    assert resumed["message"]["id"] == "message-2"
    assert interrupt_updates[-1]["status"] == "resolved"
    assert run_updates[-1]["status"] == "completed"


def test_kb_retrieval_graph_returns_wrapped_result(monkeypatch) -> None:
    retrieve = _load_kb_module("app.retrieve")
    retrieve._retrieval_graph.cache_clear()

    def fake_prepare_request(payload):
        return {"prepared": True, "base_id": payload["base_id"], "question": payload["question"], "limit": payload["limit"]}

    def fake_run_signal_retrievers(state):
        state = dict(state)
        state["signals"] = ["vector"]
        return state

    def fake_fuse_and_rerank(state):
        return RetrievalResult(items=[], stats=RetrievalStats(original_query=state["question"], selected_candidates=0, retrieval_ms=1.25))

    monkeypatch.setattr(retrieve, "_prepare_request", fake_prepare_request)
    monkeypatch.setattr(retrieve, "_run_signal_retrievers", fake_run_signal_retrievers)
    monkeypatch.setattr(retrieve, "_fuse_and_rerank", fake_fuse_and_rerank)
    retrieve._retrieval_graph.cache_clear()

    graph_state = retrieve.run_retrieval_graph({"base_id": "base-1", "question": "expense flow", "document_ids": [], "limit": 4})
    result = retrieve.retrieve_kb_result(base_id="base-1", question="expense flow", document_ids=[], limit=4)

    assert graph_state["result"].stats.original_query == "expense flow"
    assert graph_state["result"].stats.retrieval_ms == 1.25
    assert result.stats.selected_candidates == 0
