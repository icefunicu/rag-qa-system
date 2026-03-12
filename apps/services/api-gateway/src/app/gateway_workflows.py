from __future__ import annotations

from typing import Any
from uuid import uuid4

from shared.api_errors import raise_api_error
from shared.auth import CurrentUser

from .db import to_json
from .gateway_runtime import gateway_db


def workflow_kind_for_turn(*, execution_mode: str, answer_mode: str) -> str:
    cleaned_mode = str(execution_mode or "").strip().lower()
    if cleaned_mode == "agent":
        return "chat_agent"
    if str(answer_mode or "").strip().lower() == "common_knowledge":
        return "chat_common_knowledge"
    return "chat_grounded"


def serialize_workflow_run(row: dict[str, Any]) -> dict[str, Any]:
    state = dict(row.get("workflow_state_json") or {})
    return {
        "id": str(row.get("id") or ""),
        "session_id": str(row.get("session_id") or ""),
        "user_id": str(row.get("user_id") or ""),
        "execution_mode": str(row.get("execution_mode") or "grounded"),
        "workflow_kind": str(row.get("workflow_kind") or ""),
        "status": str(row.get("status") or "running"),
        "question": str(row.get("question") or ""),
        "trace_id": str(row.get("trace_id") or ""),
        "message_id": str(row.get("message_id") or ""),
        "scope_snapshot": dict(row.get("scope_snapshot_json") or {}),
        "workflow_state": state,
        "stage": str(state.get("stage") or ""),
        "workflow_events": list(row.get("workflow_events_json") or []),
        "tool_calls": list(row.get("tool_calls_json") or []),
        "graph_thread_id": str(row.get("graph_thread_id") or ""),
        "graph_run_id": str(row.get("graph_run_id") or ""),
        "current_node": str(row.get("current_node") or ""),
        "checkpoint_ns": str(row.get("checkpoint_ns") or ""),
        "checkpoint_id": str(row.get("checkpoint_id") or ""),
        "interrupt_id": str(row.get("interrupt_id") or ""),
        "interrupt_state": str(row.get("interrupt_state") or ""),
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
        "completed_at": row.get("completed_at"),
    }


def create_workflow_run(
    *,
    session_id: str,
    user: CurrentUser,
    execution_mode: str,
    workflow_kind: str,
    question: str,
    trace_id: str,
    scope_snapshot: dict[str, Any],
    workflow_state: dict[str, Any],
    workflow_events: list[dict[str, Any]] | None = None,
    tool_calls: list[dict[str, Any]] | None = None,
    graph_thread_id: str = "",
    graph_run_id: str = "",
    current_node: str = "",
    checkpoint_ns: str = "",
    checkpoint_id: str = "",
    interrupt_id: str = "",
    interrupt_state: str = "",
) -> dict[str, Any]:
    run_id = str(uuid4())
    with gateway_db.connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO chat_workflow_runs (
                    id, session_id, user_id, execution_mode, workflow_kind, status,
                    question, trace_id, scope_snapshot_json, workflow_state_json, workflow_events_json, tool_calls_json,
                    graph_thread_id, graph_run_id, current_node, checkpoint_ns, checkpoint_id, interrupt_id, interrupt_state
                )
                VALUES (
                    %s, %s, %s, %s, %s, 'running',
                    %s, %s, %s::jsonb, %s::jsonb, %s::jsonb, %s::jsonb,
                    %s, %s, %s, %s, %s, %s, %s
                )
                RETURNING *
                """,
                (
                    run_id,
                    session_id,
                    user.user_id,
                    execution_mode,
                    workflow_kind,
                    question.strip(),
                    trace_id.strip(),
                    to_json(scope_snapshot),
                    to_json(workflow_state),
                    to_json(list(workflow_events or [])),
                    to_json(list(tool_calls or [])),
                    graph_thread_id.strip(),
                    (graph_run_id or run_id).strip(),
                    current_node.strip(),
                    checkpoint_ns.strip(),
                    checkpoint_id.strip(),
                    interrupt_id.strip(),
                    interrupt_state.strip(),
                ),
            )
            row = cur.fetchone()
        conn.commit()
    return serialize_workflow_run(row or {})


def update_workflow_run(
    *,
    run_id: str,
    user: CurrentUser,
    status: str,
    workflow_state: dict[str, Any],
    workflow_events: list[dict[str, Any]] | None = None,
    tool_calls: list[dict[str, Any]] | None = None,
    message_id: str = "",
    current_node: str = "",
    checkpoint_ns: str = "",
    checkpoint_id: str = "",
    interrupt_id: str = "",
    interrupt_state: str = "",
) -> dict[str, Any]:
    next_status = str(status or "").strip().lower() or "running"
    with gateway_db.connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE chat_workflow_runs
                SET status = %s,
                    message_id = %s,
                    workflow_state_json = %s::jsonb,
                    workflow_events_json = %s::jsonb,
                    tool_calls_json = %s::jsonb,
                    current_node = %s,
                    checkpoint_ns = %s,
                    checkpoint_id = %s,
                    interrupt_id = %s,
                    interrupt_state = %s,
                    updated_at = NOW(),
                    completed_at = CASE
                        WHEN %s IN ('completed', 'failed') THEN NOW()
                        ELSE completed_at
                    END
                WHERE id = %s AND user_id = %s
                RETURNING *
                """,
                (
                    next_status,
                    message_id.strip(),
                    to_json(workflow_state),
                    to_json(list(workflow_events or [])),
                    to_json(list(tool_calls or [])),
                    current_node.strip(),
                    checkpoint_ns.strip(),
                    checkpoint_id.strip(),
                    interrupt_id.strip(),
                    interrupt_state.strip(),
                    next_status,
                    run_id,
                    user.user_id,
                ),
            )
            row = cur.fetchone()
        conn.commit()
    if row is None:
        raise_api_error(404, "chat_workflow_run_not_found", "chat workflow run not found")
    return serialize_workflow_run(row)


def list_session_workflow_runs(session_id: str, user: CurrentUser, *, load_session_fn: Any) -> list[dict[str, Any]]:
    load_session_fn(session_id, user)
    with gateway_db.connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT *
                FROM chat_workflow_runs
                WHERE session_id = %s AND user_id = %s
                ORDER BY created_at ASC
                """,
                (session_id, user.user_id),
            )
            rows = cur.fetchall()
    return [serialize_workflow_run(row) for row in rows]


def load_workflow_run_for_user(run_id: str, user: CurrentUser) -> dict[str, Any]:
    with gateway_db.connect() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM chat_workflow_runs WHERE id = %s AND user_id = %s", (run_id, user.user_id))
            row = cur.fetchone()
    if row is None:
        raise_api_error(404, "chat_workflow_run_not_found", "chat workflow run not found")
    return serialize_workflow_run(row)


def serialize_graph_interrupt(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(row.get("id") or ""),
        "run_id": str(row.get("run_id") or ""),
        "session_id": str(row.get("session_id") or ""),
        "user_id": str(row.get("user_id") or ""),
        "kind": str(row.get("kind") or ""),
        "status": str(row.get("status") or "pending"),
        "payload": dict(row.get("payload_json") or {}),
        "response": dict(row.get("response_json") or {}),
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
        "resolved_at": row.get("resolved_at"),
    }


def create_graph_interrupt(
    *,
    run_id: str,
    session_id: str,
    user: CurrentUser,
    kind: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    interrupt_id = str(uuid4())
    with gateway_db.connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO chat_graph_interrupts (id, run_id, session_id, user_id, kind, status, payload_json)
                VALUES (%s, %s, %s, %s, %s, 'pending', %s::jsonb)
                RETURNING *
                """,
                (
                    interrupt_id,
                    run_id,
                    session_id,
                    user.user_id,
                    kind.strip(),
                    to_json(payload),
                ),
            )
            row = cur.fetchone()
        conn.commit()
    return serialize_graph_interrupt(row or {})


def update_graph_interrupt(
    interrupt_id: str,
    *,
    user: CurrentUser,
    status: str,
    response_payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    next_status = str(status or "").strip().lower() or "pending"
    with gateway_db.connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE chat_graph_interrupts
                SET status = %s,
                    response_json = %s::jsonb,
                    updated_at = NOW(),
                    resolved_at = CASE WHEN %s IN ('resolved', 'dismissed') THEN NOW() ELSE resolved_at END
                WHERE id = %s AND user_id = %s
                RETURNING *
                """,
                (
                    next_status,
                    to_json(dict(response_payload or {})),
                    next_status,
                    interrupt_id,
                    user.user_id,
                ),
            )
            row = cur.fetchone()
        conn.commit()
    if row is None:
        raise_api_error(404, "chat_interrupt_not_found", "chat interrupt not found")
    return serialize_graph_interrupt(row)


def load_graph_interrupt_for_user(interrupt_id: str, user: CurrentUser) -> dict[str, Any]:
    with gateway_db.connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM chat_graph_interrupts WHERE id = %s AND user_id = %s",
                (interrupt_id, user.user_id),
            )
            row = cur.fetchone()
    if row is None:
        raise_api_error(404, "chat_interrupt_not_found", "chat interrupt not found")
    return serialize_graph_interrupt(row)
