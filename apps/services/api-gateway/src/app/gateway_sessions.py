from __future__ import annotations

from typing import Any
from uuid import uuid4

from shared.api_errors import raise_api_error
from shared.auth import CurrentUser

from .db import to_json
from .gateway_runtime import gateway_db


def load_session_for_user(session_id: str, user: CurrentUser, *, default_scope_fn: Any) -> dict[str, Any]:
    with gateway_db.connect() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM chat_sessions WHERE id = %s AND user_id = %s", (session_id, user.user_id))
            row = cur.fetchone()
    if row is None:
        raise_api_error(404, "chat_session_not_found", "chat session not found")
    if not row.get("scope_json"):
        row["scope_json"] = default_scope_fn()
    return row


def serialize_chat_message(row: dict[str, Any]) -> dict[str, Any]:
    role = str(row.get("role") or "")
    content = str(row.get("question") or "") if role == "user" else str(row.get("answer") or "")
    usage_payload = dict(row.get("usage_json") or {})
    meta_payload = dict(usage_payload.get("_meta") or {})
    return {
        "id": str(row.get("id") or ""),
        "session_id": str(row.get("session_id") or ""),
        "role": role,
        "content": content,
        "question": str(row.get("question") or ""),
        "answer": str(row.get("answer") or ""),
        "answer_mode": str(row.get("answer_mode") or ""),
        "execution_mode": str((row.get("scope_snapshot_json") or {}).get("execution_mode") or "grounded"),
        "evidence_status": str(row.get("evidence_status") or ""),
        "grounding_score": float(row.get("grounding_score") or 0.0),
        "refusal_reason": str(row.get("refusal_reason") or ""),
        "citations": list(row.get("citations_json") or []),
        "evidence_path": list(row.get("evidence_path_json") or []),
        "scope_snapshot": dict(row.get("scope_snapshot_json") or {}),
        "provider": str(row.get("provider") or ""),
        "model": str(row.get("model") or ""),
        "usage": usage_payload,
        "trace_id": str(meta_payload.get("trace_id") or ""),
        "retrieval": dict(meta_payload.get("retrieval") or {}),
        "latency": dict(meta_payload.get("latency") or {}),
        "cost": dict(meta_payload.get("cost") or {}),
        "created_at": row.get("created_at"),
    }


def list_session_messages(session_id: str, user: CurrentUser, *, load_session_fn: Any) -> list[dict[str, Any]]:
    load_session_fn(session_id, user)
    with gateway_db.connect() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM chat_messages WHERE session_id = %s AND user_id = %s ORDER BY created_at ASC", (session_id, user.user_id))
            rows = cur.fetchall()
    return [serialize_chat_message(row) for row in rows]


def recent_history_messages(session_id: str, user: CurrentUser, *, load_session_fn: Any, limit: int = 8) -> list[dict[str, Any]]:
    load_session_fn(session_id, user)
    with gateway_db.connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT *
                FROM (
                    SELECT *
                    FROM chat_messages
                    WHERE session_id = %s AND user_id = %s
                    ORDER BY created_at DESC
                    LIMIT %s
                ) AS recent_messages
                ORDER BY created_at ASC
                """,
                (session_id, user.user_id, limit),
            )
            rows = cur.fetchall()
    return [serialize_chat_message(row) for row in rows]


def persist_chat_turn(
    *,
    session_id: str,
    user: CurrentUser,
    question: str,
    session_scope: dict[str, Any],
    response_payload: dict[str, Any],
    compact_text_fn: Any,
    usage_with_meta_fn: Any,
) -> dict[str, Any]:
    user_message_id = str(uuid4())
    assistant_message_id = str(uuid4())
    title = compact_text_fn(question, 48)
    with gateway_db.connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE chat_sessions
                SET scope_json = %s::jsonb,
                    title = CASE WHEN title = '' THEN %s ELSE title END,
                    updated_at = NOW()
                WHERE id = %s AND user_id = %s
                """,
                (to_json(session_scope), title, session_id, user.user_id),
            )
            cur.execute(
                "INSERT INTO chat_messages (id, session_id, user_id, role, question, scope_snapshot_json) VALUES (%s, %s, %s, 'user', %s, %s::jsonb)",
                (user_message_id, session_id, user.user_id, question.strip(), to_json(session_scope)),
            )
            cur.execute(
                """
                INSERT INTO chat_messages (
                    id, session_id, user_id, role, answer, answer_mode, evidence_status,
                    grounding_score, refusal_reason, citations_json, evidence_path_json,
                    scope_snapshot_json, provider, model, usage_json
                )
                VALUES (
                    %s, %s, %s, 'assistant', %s, %s, %s,
                    %s, %s, %s::jsonb, %s::jsonb,
                    %s::jsonb, %s, %s, %s::jsonb
                )
                """,
                (
                    assistant_message_id,
                    session_id,
                    user.user_id,
                    response_payload["answer"],
                    response_payload["answer_mode"],
                    response_payload["evidence_status"],
                    response_payload["grounding_score"],
                    response_payload["refusal_reason"],
                    to_json(response_payload["citations"]),
                    to_json(response_payload["evidence_path"]),
                    to_json(session_scope),
                    response_payload["provider"],
                    response_payload["model"],
                    to_json(
                        usage_with_meta_fn(
                            response_payload["usage"],
                            trace_id=str(response_payload.get("trace_id") or ""),
                            retrieval=dict(response_payload.get("retrieval") or {}),
                            latency=dict(response_payload.get("latency") or {}),
                            cost=dict(response_payload.get("cost") or {}),
                        )
                    ),
                ),
            )
        conn.commit()
    return serialize_chat_message(
        {
            "id": assistant_message_id,
            "session_id": session_id,
            "role": "assistant",
            "question": "",
            "answer": response_payload["answer"],
            "answer_mode": response_payload["answer_mode"],
            "evidence_status": response_payload["evidence_status"],
            "grounding_score": response_payload["grounding_score"],
            "refusal_reason": response_payload["refusal_reason"],
            "citations_json": response_payload["citations"],
            "evidence_path_json": response_payload["evidence_path"],
            "scope_snapshot_json": session_scope,
            "provider": response_payload["provider"],
            "model": response_payload["model"],
            "usage_json": usage_with_meta_fn(
                response_payload["usage"],
                trace_id=str(response_payload.get("trace_id") or ""),
                retrieval=dict(response_payload.get("retrieval") or {}),
                latency=dict(response_payload.get("latency") or {}),
                cost=dict(response_payload.get("cost") or {}),
            ),
            "created_at": None,
        }
    )
