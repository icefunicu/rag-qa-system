from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from fastapi import Request
from pydantic import BaseModel

from shared.api_errors import raise_api_error
from shared.auth import CurrentUser
from shared.idempotency import IDEMPOTENCY_HEADER, build_request_hash, normalize_idempotency_key


@dataclass(frozen=True)
class IdempotencyState:
    key: str = ""
    request_scope: str = ""
    request_hash: str = ""
    replay_payload: dict[str, Any] | None = None

    @property
    def enabled(self) -> bool:
        return bool(self.key)


def kb_readiness_checks(*, db: Any, storage: Any, vector_store_checker: Any | None = None) -> dict[str, Any]:
    checks: dict[str, Any] = {}
    try:
        with db.connect() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1 AS ok")
                cur.fetchone()
        checks["database"] = {"status": "ok"}
    except Exception as exc:
        checks["database"] = {"status": "failed", "detail": str(exc)}

    try:
        storage.check_bucket_access()
        checks["object_storage"] = {"status": "ok"}
    except Exception as exc:
        checks["object_storage"] = {"status": "failed", "detail": str(exc)}

    if vector_store_checker is not None:
        try:
            checks["vector_store"] = {"status": "ok", **dict(vector_store_checker() or {})}
        except Exception as exc:
            checks["vector_store"] = {"status": "failed", "detail": str(exc)}

    return checks


def serialize_timestamp(value: Any) -> str:
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value or "")


def _normalize_idempotency_payload(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump()
    if isinstance(value, dict):
        return {str(key): _normalize_idempotency_payload(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_normalize_idempotency_payload(item) for item in value]
    return value


def _idempotency_conflict(message: str) -> None:
    raise_api_error(409, "idempotency_conflict", message)


def begin_kb_idempotency(
    request: Request,
    user: CurrentUser,
    *,
    request_scope: str,
    payload: dict[str, Any],
    db: Any,
    ttl_hours: int,
    counter: Any,
) -> IdempotencyState:
    key = normalize_idempotency_key(request.headers.get(IDEMPOTENCY_HEADER, ""))
    if not key:
        return IdempotencyState()

    request_hash = build_request_hash(request_scope, _normalize_idempotency_payload(payload))
    with db.connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO kb_idempotency_keys (
                    idempotency_key, request_scope, actor_user_id, request_hash, status, expires_at
                )
                VALUES (%s, %s, %s, %s, 'processing', NOW() + (%s || ' hours')::interval)
                ON CONFLICT DO NOTHING
                RETURNING idempotency_key
                """,
                (key, request_scope, user.user_id, request_hash, ttl_hours),
            )
            inserted = cur.fetchone() is not None
            if not inserted:
                cur.execute(
                    """
                    SELECT *
                    FROM kb_idempotency_keys
                    WHERE idempotency_key = %s
                      AND request_scope = %s
                      AND actor_user_id = %s
                    """,
                    (key, request_scope, user.user_id),
                )
                row = cur.fetchone()
                if row is None:
                    _idempotency_conflict("idempotency state could not be resolved")
                if str(row.get("request_hash") or "") != request_hash:
                    counter.labels("conflict", request_scope).inc()
                    _idempotency_conflict("idempotency key already used with a different request payload")
                status_value = str(row.get("status") or "")
                if status_value == "succeeded":
                    counter.labels("replay", request_scope).inc()
                    return IdempotencyState(
                        key=key,
                        request_scope=request_scope,
                        request_hash=request_hash,
                        replay_payload=dict(row.get("response_json") or {}),
                    )
                if status_value == "processing":
                    counter.labels("in_progress", request_scope).inc()
                    _idempotency_conflict("another request with the same idempotency key is still processing")
                cur.execute(
                    """
                    UPDATE kb_idempotency_keys
                    SET status = 'processing',
                        response_json = '{}'::jsonb,
                        resource_id = '',
                        expires_at = NOW() + (%s || ' hours')::interval,
                        updated_at = NOW()
                    WHERE idempotency_key = %s
                      AND request_scope = %s
                      AND actor_user_id = %s
                    """,
                    (ttl_hours, key, request_scope, user.user_id),
                )
                counter.labels("retry", request_scope).inc()
            else:
                counter.labels("miss", request_scope).inc()
        conn.commit()
    return IdempotencyState(key=key, request_scope=request_scope, request_hash=request_hash)


def complete_kb_idempotency(
    state: IdempotencyState,
    user: CurrentUser,
    *,
    response_payload: dict[str, Any],
    resource_id: str = "",
    db: Any,
    to_json: Any,
    counter: Any,
) -> None:
    if not state.enabled:
        return
    with db.connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE kb_idempotency_keys
                SET status = 'succeeded',
                    response_json = %s::jsonb,
                    resource_id = %s,
                    updated_at = NOW()
                WHERE idempotency_key = %s
                  AND request_scope = %s
                  AND actor_user_id = %s
                """,
                (to_json(response_payload), resource_id, state.key, state.request_scope, user.user_id),
            )
        conn.commit()
    counter.labels("success", state.request_scope).inc()


def fail_kb_idempotency(
    state: IdempotencyState,
    user: CurrentUser,
    exc: Exception,
    *,
    db: Any,
    to_json: Any,
    counter: Any,
) -> None:
    if not state.enabled:
        return
    status_code = getattr(exc, "status_code", 500)
    detail = getattr(exc, "detail", str(exc))
    payload = {
        "status_code": int(status_code),
        "detail": detail if isinstance(detail, (dict, list)) else str(detail),
    }
    with db.connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE kb_idempotency_keys
                SET status = 'failed',
                    response_json = %s::jsonb,
                    updated_at = NOW()
                WHERE idempotency_key = %s
                  AND request_scope = %s
                  AND actor_user_id = %s
                """,
                (to_json(payload), state.key, state.request_scope, user.user_id),
            )
        conn.commit()
    counter.labels("failed", state.request_scope).inc()


def refresh_kb_metrics_snapshot(
    *,
    db: Any,
    jobs_gauge: Any,
    dead_letter_gauge: Any,
) -> None:
    statuses = ("queued", "retry", "processing", "done", "failed", "dead_letter")
    counts = {status: 0 for status in statuses}
    with db.connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT status, COUNT(*) AS total
                FROM kb_ingest_jobs
                GROUP BY status
                """
            )
            for row in cur.fetchall():
                counts[str(row.get("status") or "")] = int(row.get("total") or 0)
    for status in statuses:
        jobs_gauge.labels(status).set(float(counts.get(status, 0)))
    dead_letter_gauge.set(float(counts.get("dead_letter", 0)))


def record_kb_audit_event(
    *,
    db: Any,
    to_json: Any,
    logger: Any,
    current_trace_id: Any,
    action: str,
    outcome: str,
    request: Request | None = None,
    user: CurrentUser | None = None,
    actor_email: str = "",
    resource_type: str = "",
    resource_id: str = "",
    scope: str = "",
    details: dict[str, Any] | None = None,
) -> None:
    try:
        with db.connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO kb_audit_events (
                        actor_user_id, actor_email, actor_role, action, resource_type,
                        resource_id, scope, outcome, trace_id, request_path, details_json
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)
                    """,
                    (
                        str(user.user_id if user else ""),
                        str(user.email if user else actor_email),
                        str(user.role if user else ""),
                        action,
                        resource_type,
                        resource_id,
                        scope,
                        outcome,
                        current_trace_id(),
                        str(request.url.path if request else ""),
                        to_json(details or {}),
                    ),
                )
            conn.commit()
    except Exception:
        logger.exception("kb audit write failed action=%s outcome=%s", action, outcome)


def require_permission(
    *,
    request: Request,
    user: CurrentUser,
    permission: str,
    action: str,
    has_permission_fn: Any,
    audit_writer: Any,
    resource_type: str = "",
    resource_id: str = "",
    details: dict[str, Any] | None = None,
) -> None:
    if has_permission_fn(user, permission):
        return
    audit_writer(
        action=action,
        outcome="denied",
        request=request,
        user=user,
        resource_type=resource_type,
        resource_id=resource_id,
        scope="permission",
        details={"permission": permission, **(details or {})},
    )
    raise_api_error(403, "permission_denied", f"missing permission: {permission}")


def serialize_kb_audit_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(row.get("id") or ""),
        "service": "kb-service",
        "actor_user_id": str(row.get("actor_user_id") or ""),
        "actor_email": str(row.get("actor_email") or ""),
        "actor_role": str(row.get("actor_role") or ""),
        "action": str(row.get("action") or ""),
        "resource_type": str(row.get("resource_type") or ""),
        "resource_id": str(row.get("resource_id") or ""),
        "scope": str(row.get("scope") or ""),
        "outcome": str(row.get("outcome") or ""),
        "trace_id": str(row.get("trace_id") or ""),
        "request_path": str(row.get("request_path") or ""),
        "details": dict(row.get("details_json") or {}),
        "created_at": serialize_timestamp(row.get("created_at")),
    }


def query_kb_audit_events(
    *,
    db: Any,
    actor_user_id: str = "",
    resource_type: str = "",
    resource_id: str = "",
    action: str = "",
    outcome: str = "",
    created_from: str = "",
    created_to: str = "",
    limit: int,
) -> list[dict[str, Any]]:
    clauses = ["TRUE"]
    params: list[Any] = []
    if actor_user_id:
        clauses.append("actor_user_id = %s")
        params.append(actor_user_id)
    if resource_type:
        clauses.append("resource_type = %s")
        params.append(resource_type)
    if resource_id:
        clauses.append("resource_id = %s")
        params.append(resource_id)
    if action:
        clauses.append("action = %s")
        params.append(action)
    if outcome:
        clauses.append("outcome = %s")
        params.append(outcome)
    if created_from:
        clauses.append("created_at >= %s::timestamptz")
        params.append(created_from)
    if created_to:
        clauses.append("created_at <= %s::timestamptz")
        params.append(created_to)
    params.append(limit)
    with db.connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT *
                FROM kb_audit_events
                WHERE {" AND ".join(clauses)}
                ORDER BY created_at DESC
                LIMIT %s
                """,
                tuple(params),
            )
            return [serialize_kb_audit_row(row) for row in cur.fetchall()]


def can_manage_all_kb(user: CurrentUser, *, has_permission_fn: Any, manage_permission: str) -> bool:
    return has_permission_fn(user, manage_permission)
