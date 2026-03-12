from __future__ import annotations

import time
import asyncio
from contextlib import contextmanager
from dataclasses import dataclass
import os
from types import SimpleNamespace
from typing import Any, Iterator, TypedDict

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.graph import END, StateGraph
from langgraph.types import Command, interrupt

from shared.auth import AuthUser, serialize_user

from .gateway_answering import generate_grounded_answer
from .gateway_chat_service import build_chat_response_payload, finalize_chat_message, prepare_chat_message
from .gateway_runtime import gateway_db, logger
from .gateway_schemas import ChatScopePayload, SendMessageRequest
from .gateway_workflows import (
    create_graph_interrupt,
    create_workflow_run,
    load_graph_interrupt_for_user,
    load_workflow_run_for_user,
    update_graph_interrupt,
    update_workflow_run,
)

_MEMORY_SAVER = InMemorySaver()


class ChatGraphState(TypedDict, total=False):
    session_id: str
    request_scope: str
    payload: dict[str, Any]
    user_context: dict[str, Any]
    request_context: dict[str, Any]
    prepared: dict[str, Any]
    response_payload: dict[str, Any]
    result: dict[str, Any]
    generation_checkpoint: dict[str, Any]
    verification: dict[str, Any]
    human_review: dict[str, Any]
    step_events: list[dict[str, Any]]
    status: str
    current_node: str


@dataclass(frozen=True)
class GatewayGraphDependencies:
    load_session_fn: Any
    default_scope_fn: Any
    resolve_scope_snapshot_fn: Any
    recent_history_messages_fn: Any
    retrieve_scope_evidence_fn: Any
    fetch_corpus_documents_fn: Any
    persist_chat_turn_fn: Any
    session_cost_summary_fn: Any | None = None


def ensure_gateway_graph_schema() -> None:
    mode = str(os.getenv("GATEWAY_GRAPH_CHECKPOINTER", "postgres")).strip().lower()
    if mode == "memory":
        return
    with PostgresSaver.from_conn_string(gateway_db.dsn) as saver:
        saver.setup()


@contextmanager
def _graph_checkpointer() -> Iterator[Any]:
    mode = str(os.getenv("GATEWAY_GRAPH_CHECKPOINTER", "postgres")).strip().lower()
    if mode == "memory":
        yield _MEMORY_SAVER
        return
    with PostgresSaver.from_conn_string(gateway_db.dsn) as saver:
        yield saver


def _append_step_event(state: ChatGraphState, *, node: str, status: str, details: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    events = list(state.get("step_events") or [])
    events.append({"node": node, "status": status, **dict(details or {})})
    return events


def _deserialize_user(payload: dict[str, Any]) -> AuthUser:
    permissions = tuple(str(item).strip() for item in list(payload.get("permissions") or []) if str(item).strip())
    return AuthUser(
        user_id=str(payload.get("id") or ""),
        email=str(payload.get("email") or ""),
        role=str(payload.get("role") or ""),
        permissions=permissions,
        role_version=int(payload.get("role_version") or 1),
    )


def _request_proxy(request_context: dict[str, Any]) -> Any:
    return SimpleNamespace(url=SimpleNamespace(path=str(request_context.get("path") or "")))


def _payload_model(payload: dict[str, Any]) -> SendMessageRequest:
    scope = payload.get("scope")
    scope_model = ChatScopePayload(**dict(scope)) if isinstance(scope, dict) and scope else None
    return SendMessageRequest(
        question=str(payload.get("question") or ""),
        scope=scope_model,
        execution_mode=payload.get("execution_mode"),
    )


def _serialize_prepared(prepared: dict[str, Any]) -> dict[str, Any]:
    payload = prepared.get("payload")
    if isinstance(payload, dict):
        payload_dict = dict(payload)
    elif hasattr(payload, "model_dump"):
        payload_dict = payload.model_dump()
    else:
        payload_dict = {
            "question": str(getattr(payload, "question", "")),
            "scope": getattr(payload, "scope", None).model_dump() if getattr(payload, "scope", None) is not None else None,
            "execution_mode": getattr(payload, "execution_mode", None),
        }
    data = dict(prepared)
    data["payload"] = payload_dict
    return data


def _deserialize_prepared(prepared: dict[str, Any]) -> dict[str, Any]:
    payload = dict(prepared.get("payload") or {})
    restored = dict(prepared)
    restored["payload"] = SimpleNamespace(**payload)
    return restored


def _build_human_review(prepared: dict[str, Any]) -> dict[str, Any]:
    aggregate = dict(((prepared.get("retrieval_meta") or {}).get("aggregate") or {}))
    scope_snapshot = dict(prepared.get("scope_snapshot") or {})
    if bool(aggregate.get("empty_scope")):
        return {
            "kind": "ambiguous_scope",
            "title": "当前没有可用知识范围",
            "detail": "请补充问题或允许调整范围后继续。",
            "question": str((prepared.get("payload") or {}).get("question") or ""),
            "allow_common_knowledge": bool(scope_snapshot.get("allow_common_knowledge")),
        }
    if (
        str(prepared.get("execution_mode") or "") == "agent"
        and not list(prepared.get("evidence") or [])
        and str(prepared.get("answer_mode") or "") == "refusal"
        and not bool(scope_snapshot.get("allow_common_knowledge"))
    ):
        return {
            "kind": "insufficient_evidence",
            "title": "证据不足，需要人工确认下一步",
            "detail": "可以改写问题，或允许在本轮使用常识补充回答。",
            "question": str((prepared.get("payload") or {}).get("question") or ""),
            "allow_common_knowledge": False,
        }
    return {}


def _verification_payload(response_payload: dict[str, Any]) -> dict[str, Any]:
    citations = list(response_payload.get("citations") or [])
    answer = str(response_payload.get("answer") or "")
    has_marker = any(f"[{index}]" in answer for index in range(1, len(citations) + 1))
    status = "passed"
    if citations and not has_marker:
        status = "warning"
    return {
        "status": status,
        "citation_count": len(citations),
        "has_inline_marker": has_marker,
    }


def _build_workflow_state(state: ChatGraphState, *, stage: str, interrupt_payload: dict[str, Any] | None = None) -> dict[str, Any]:
    prepared = dict(state.get("prepared") or {})
    response_payload = dict(state.get("response_payload") or {})
    result = dict(state.get("result") or {})
    return {
        "stage": stage,
        "status": str(state.get("status") or ""),
        "current_node": str(state.get("current_node") or ""),
        "payload": dict(state.get("payload") or {}),
        "execution_mode": str(prepared.get("execution_mode") or ""),
        "answer_mode": str(prepared.get("answer_mode") or response_payload.get("answer_mode") or ""),
        "scope_snapshot": dict(prepared.get("scope_snapshot") or {}),
        "retrieval": dict(prepared.get("retrieval_meta") or response_payload.get("retrieval") or {}),
        "verification": dict(state.get("verification") or {}),
        "step_events": list(state.get("step_events") or []),
        "interrupt": dict(interrupt_payload or {}),
        "message_id": str(((result.get("message") or {}) if isinstance(result, dict) else {}).get("id") or ""),
    }


def _tool_calls_from_state(state: ChatGraphState) -> list[dict[str, Any]]:
    prepared = dict(state.get("prepared") or {})
    agent_meta = dict(((prepared.get("retrieval_meta") or {}).get("agent") or {}))
    return list(agent_meta.get("tool_calls") or [])


def _checkpoint_id(snapshot: Any) -> str:
    config = dict(getattr(snapshot, "config", {}) or {})
    configurable = dict(config.get("configurable") or {})
    return str(configurable.get("checkpoint_id") or "")


def _interrupt_payload(snapshot: Any) -> dict[str, Any]:
    for task in list(getattr(snapshot, "tasks", ()) or ()):
        interrupts = list(getattr(task, "interrupts", ()) or ())
        if not interrupts:
            continue
        interrupt_item = interrupts[0]
        return dict(getattr(interrupt_item, "value", {}) or {})
    return {}


def build_gateway_chat_graph(*, deps: GatewayGraphDependencies, checkpointer: Any) -> Any:
    def prepare_turn(state: ChatGraphState) -> dict[str, Any]:
        user = _deserialize_user(dict(state.get("user_context") or {}))
        payload_model = _payload_model(dict(state.get("payload") or {}))
        prepared = asyncio.run(
            prepare_chat_message(
                session_id=str(state.get("session_id") or ""),
                payload=payload_model,
                request=_request_proxy(dict(state.get("request_context") or {})),
                request_scope=str(state.get("request_scope") or "chat.graph.run"),
                user=user,
                load_session_fn=deps.load_session_fn,
                default_scope_fn=deps.default_scope_fn,
                resolve_scope_snapshot_fn=deps.resolve_scope_snapshot_fn,
                recent_history_messages_fn=deps.recent_history_messages_fn,
                retrieve_scope_evidence_fn=deps.retrieve_scope_evidence_fn,
                fetch_corpus_documents_fn=deps.fetch_corpus_documents_fn,
                session_cost_summary_fn=deps.session_cost_summary_fn,
            )
        )
        serialized = _serialize_prepared(prepared)
        human_review = _build_human_review(serialized)
        return {
            "prepared": serialized,
            "human_review": human_review,
            "status": "interrupted" if human_review else "prepared",
            "current_node": "prepare_turn",
            "step_events": _append_step_event(
                state,
                node="prepare_turn",
                status="interrupted" if human_review else "completed",
                details={
                    "execution_mode": str(serialized.get("execution_mode") or ""),
                    "answer_mode": str(serialized.get("answer_mode") or ""),
                    "evidence_count": len(list(serialized.get("evidence") or [])),
                },
            ),
        }

    def human_review_turn(state: ChatGraphState) -> dict[str, Any]:
        prompt = dict(state.get("human_review") or {})
        response = interrupt(prompt)
        next_payload = dict(state.get("payload") or {})
        if str(response.get("question") or "").strip():
            next_payload["question"] = str(response.get("question") or "").strip()
        if response.get("allow_common_knowledge") is not None:
            scope = dict(next_payload.get("scope") or {})
            scope["allow_common_knowledge"] = bool(response.get("allow_common_knowledge"))
            next_payload["scope"] = scope
        return {
            "payload": next_payload,
            "human_review": {},
            "status": "resumed",
            "current_node": "human_review_turn",
            "step_events": _append_step_event(
                state,
                node="human_review_turn",
                status="resumed",
                details={"response_keys": sorted(str(key) for key in dict(response).keys())},
            ),
        }

    def generate_answer(state: ChatGraphState) -> dict[str, Any]:
        prepared = _deserialize_prepared(dict(state.get("prepared") or {}))
        generation_started = time.perf_counter()
        answer_payload = asyncio.run(
            generate_grounded_answer(
                question=str(prepared.get("contextualized_question") or ""),
                history=list(prepared.get("history") or []),
                evidence=list(prepared.get("evidence") or []),
                answer_mode=str(prepared.get("answer_mode") or ""),
                safety=dict(prepared.get("safety") or {}),
                settings_prompt_append=str(prepared.get("settings_prompt_append") or ""),
            )
        )
        generation_ms = round((time.perf_counter() - generation_started) * 1000.0, 3)
        response_payload = build_chat_response_payload(
            prepared=prepared,
            answer_payload=answer_payload,
            generation_ms=generation_ms,
        )
        verification = _verification_payload(response_payload)
        return {
            "generation_checkpoint": {"answer_payload": answer_payload, "generation_ms": generation_ms},
            "response_payload": response_payload,
            "verification": verification,
            "status": "generated",
            "current_node": "generate_answer",
            "step_events": _append_step_event(
                state,
                node="generate_answer",
                status="completed",
                details={"verification_status": verification["status"]},
            ),
        }

    def persist_turn(state: ChatGraphState) -> dict[str, Any]:
        prepared = _deserialize_prepared(dict(state.get("prepared") or {}))
        result = finalize_chat_message(
            prepared=prepared,
            request=_request_proxy(dict(state.get("request_context") or {})),
            user=_deserialize_user(dict(state.get("user_context") or {})),
            response_payload=dict(state.get("response_payload") or {}),
            persist_chat_turn_fn=deps.persist_chat_turn_fn,
        )
        return {
            "result": result,
            "status": "completed",
            "current_node": "persist_turn",
            "step_events": _append_step_event(
                state,
                node="persist_turn",
                status="completed",
                details={"message_id": str(((result.get("message") or {}) if isinstance(result, dict) else {}).get("id") or "")},
            ),
        }

    def route_after_prepare(state: ChatGraphState) -> str:
        return "human_review_turn" if dict(state.get("human_review") or {}) else "generate_answer"

    graph = StateGraph(ChatGraphState)
    graph.add_node("prepare_turn", prepare_turn)
    graph.add_node("human_review_turn", human_review_turn)
    graph.add_node("generate_answer", generate_answer)
    graph.add_node("persist_turn", persist_turn)
    graph.set_entry_point("prepare_turn")
    graph.add_conditional_edges(
        "prepare_turn",
        route_after_prepare,
        {
            "human_review_turn": "human_review_turn",
            "generate_answer": "generate_answer",
        },
    )
    graph.add_edge("human_review_turn", "prepare_turn")
    graph.add_edge("generate_answer", "persist_turn")
    graph.add_edge("persist_turn", END)
    return graph.compile(checkpointer=checkpointer)


def _graph_config(*, run_id: str) -> dict[str, Any]:
    return {"configurable": {"thread_id": run_id}}


async def run_gateway_graph_turn(
    *,
    session_id: str,
    payload: dict[str, Any],
    request_scope: str,
    user: AuthUser,
    request_path: str,
    deps: GatewayGraphDependencies,
) -> dict[str, Any]:
    run = create_workflow_run(
        session_id=session_id,
        user=user,
        execution_mode=str(payload.get("execution_mode") or "grounded"),
        workflow_kind="chat_graph",
        question=str(payload.get("question") or ""),
        trace_id="",
        scope_snapshot=dict(((payload.get("scope") or {}) if isinstance(payload.get("scope"), dict) else {})),
        workflow_state={"stage": "queued"},
        workflow_events=[],
        tool_calls=[],
        graph_thread_id=session_id,
        checkpoint_ns="",
    )
    with _graph_checkpointer() as checkpointer:
        compiled = build_gateway_chat_graph(deps=deps, checkpointer=checkpointer)
        state: ChatGraphState = {
            "session_id": session_id,
            "request_scope": request_scope,
            "payload": dict(payload),
            "user_context": serialize_user(user),
            "request_context": {"path": request_path},
            "status": "running",
            "current_node": "prepare_turn",
            "step_events": [],
        }
        try:
            result = await asyncio.to_thread(compiled.invoke, state, _graph_config(run_id=run["id"]))
            snapshot = compiled.get_state(_graph_config(run_id=run["id"]))
        except Exception as exc:
            update_workflow_run(
                run_id=run["id"],
                user=user,
                status="failed",
                workflow_state={"stage": "failed", "error": {"type": exc.__class__.__name__, "detail": str(exc)}},
                workflow_events=[],
                tool_calls=[],
                current_node="failed",
                checkpoint_ns=run["id"],
            )
            raise
    values = dict(getattr(snapshot, "values", {}) or {})
    checkpoint_id = _checkpoint_id(snapshot)
    interrupt_payload = _interrupt_payload(snapshot)
    if interrupt_payload:
        interrupt_row = create_graph_interrupt(
            run_id=run["id"],
            session_id=session_id,
            user=user,
            kind=str(interrupt_payload.get("kind") or "human_review"),
            payload=interrupt_payload,
        )
        workflow_state = _build_workflow_state(values, stage="interrupted", interrupt_payload=interrupt_payload)
        run = update_workflow_run(
            run_id=run["id"],
            user=user,
            status="interrupted",
            workflow_state=workflow_state,
            workflow_events=list(values.get("step_events") or []),
            tool_calls=_tool_calls_from_state(values),
            current_node=str(values.get("current_node") or "human_review_turn"),
            checkpoint_ns=run["id"],
            checkpoint_id=checkpoint_id,
            interrupt_id=interrupt_row["id"],
            interrupt_state="pending",
        )
        return {
            "status": "interrupted",
            "thread_id": session_id,
            "run": run,
            "interrupt": interrupt_row,
            "step_events": list(values.get("step_events") or []),
            "retrieval": dict(((values.get("prepared") or {}).get("retrieval_meta") or {})),
            "verification": dict(values.get("verification") or {}),
        }
    workflow_state = _build_workflow_state(values, stage="completed")
    run = update_workflow_run(
        run_id=run["id"],
        user=user,
        status="completed",
        workflow_state=workflow_state,
        workflow_events=list(values.get("step_events") or []),
        tool_calls=_tool_calls_from_state(values),
        message_id=str((((values.get("result") or {}).get("message") or {}) if isinstance(values.get("result"), dict) else {}).get("id") or ""),
        current_node=str(values.get("current_node") or "persist_turn"),
        checkpoint_ns=run["id"],
        checkpoint_id=checkpoint_id,
    )
    payload_out = dict(values.get("result") or result or {})
    payload_out["status"] = "completed"
    payload_out["thread_id"] = session_id
    payload_out["run"] = run
    payload_out["step_events"] = list(values.get("step_events") or [])
    payload_out["verification"] = dict(values.get("verification") or {})
    return payload_out


async def resume_gateway_graph_turn(
    *,
    run_id: str,
    user: AuthUser,
    response_payload: dict[str, Any],
    deps: GatewayGraphDependencies,
    interrupt_id: str = "",
) -> dict[str, Any]:
    run = load_workflow_run_for_user(run_id, user)
    if str(run.get("status") or "") != "interrupted":
        raise ValueError("only interrupted runs can be resumed")
    if interrupt_id:
        update_graph_interrupt(interrupt_id, user=user, status="resolved", response_payload=response_payload)
    with _graph_checkpointer() as checkpointer:
        compiled = build_gateway_chat_graph(deps=deps, checkpointer=checkpointer)
        try:
            result = await asyncio.to_thread(
                compiled.invoke,
                Command(resume=dict(response_payload or {})),
                _graph_config(run_id=run_id),
            )
            snapshot = compiled.get_state(_graph_config(run_id=run_id))
        except Exception as exc:
            update_workflow_run(
                run_id=run_id,
                user=user,
                status="failed",
                workflow_state={"stage": "failed", "error": {"type": exc.__class__.__name__, "detail": str(exc)}},
                workflow_events=[],
                tool_calls=[],
                current_node="failed",
                checkpoint_ns=run_id,
            )
            raise
    values = dict(getattr(snapshot, "values", {}) or {})
    checkpoint_id = _checkpoint_id(snapshot)
    next_interrupt = _interrupt_payload(snapshot)
    if next_interrupt:
        interrupt_row = create_graph_interrupt(
            run_id=run_id,
            session_id=str(run.get("session_id") or ""),
            user=user,
            kind=str(next_interrupt.get("kind") or "human_review"),
            payload=next_interrupt,
        )
        workflow_state = _build_workflow_state(values, stage="interrupted", interrupt_payload=next_interrupt)
        run = update_workflow_run(
            run_id=run_id,
            user=user,
            status="interrupted",
            workflow_state=workflow_state,
            workflow_events=list(values.get("step_events") or []),
            tool_calls=_tool_calls_from_state(values),
            current_node=str(values.get("current_node") or "human_review_turn"),
            checkpoint_ns=run_id,
            checkpoint_id=checkpoint_id,
            interrupt_id=interrupt_row["id"],
            interrupt_state="pending",
        )
        return {
            "status": "interrupted",
            "thread_id": str(run.get("session_id") or ""),
            "run": run,
            "interrupt": interrupt_row,
            "step_events": list(values.get("step_events") or []),
            "retrieval": dict(((values.get("prepared") or {}).get("retrieval_meta") or {})),
            "verification": dict(values.get("verification") or {}),
        }
    workflow_state = _build_workflow_state(values, stage="completed")
    run = update_workflow_run(
        run_id=run_id,
        user=user,
        status="completed",
        workflow_state=workflow_state,
        workflow_events=list(values.get("step_events") or []),
        tool_calls=_tool_calls_from_state(values),
        message_id=str((((values.get("result") or {}).get("message") or {}) if isinstance(values.get("result"), dict) else {}).get("id") or ""),
        current_node=str(values.get("current_node") or "persist_turn"),
        checkpoint_ns=run_id,
        checkpoint_id=checkpoint_id,
        interrupt_id="",
        interrupt_state="resolved",
    )
    payload_out = dict(values.get("result") or result or {})
    payload_out["status"] = "completed"
    payload_out["thread_id"] = str(run.get("session_id") or "")
    payload_out["run"] = run
    payload_out["step_events"] = list(values.get("step_events") or [])
    payload_out["verification"] = dict(values.get("verification") or {})
    return payload_out


def load_interrupt_for_run(*, interrupt_id: str, user: AuthUser) -> dict[str, Any]:
    return load_graph_interrupt_for_user(interrupt_id, user)
