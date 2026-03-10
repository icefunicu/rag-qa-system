from __future__ import annotations

from typing import Any

from fastapi import Request

from shared.auth import CurrentUser, has_permission
from shared.tracing import current_trace_id

from .db import to_json
from .kb_runtime import (
    IDEMPOTENCY_TTL_HOURS,
    KB_DEAD_LETTER_GAUGE,
    KB_IDEMPOTENCY_TOTAL,
    KB_INGEST_JOBS_GAUGE,
    KB_MANAGE_PERMISSION,
    db,
    logger,
    storage,
)
from .vector_store import check_vector_store
from .kb_support import (
    IdempotencyState,
    begin_kb_idempotency,
    can_manage_all_kb,
    complete_kb_idempotency,
    fail_kb_idempotency,
    kb_readiness_checks,
    query_kb_audit_events,
    record_kb_audit_event,
    refresh_kb_metrics_snapshot,
    require_permission,
)


def check_readiness() -> dict[str, Any]:
    return kb_readiness_checks(db=db, storage=storage, vector_store_checker=check_vector_store)


def refresh_metrics_snapshot() -> None:
    refresh_kb_metrics_snapshot(
        db=db,
        jobs_gauge=KB_INGEST_JOBS_GAUGE,
        dead_letter_gauge=KB_DEAD_LETTER_GAUGE,
    )


def audit_event(
    *,
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
    record_kb_audit_event(
        db=db,
        to_json=to_json,
        logger=logger,
        current_trace_id=current_trace_id,
        action=action,
        outcome=outcome,
        request=request,
        user=user,
        actor_email=actor_email,
        resource_type=resource_type,
        resource_id=resource_id,
        scope=scope,
        details=details,
    )


def require_kb_permission(
    request: Request,
    user: CurrentUser,
    permission: str,
    *,
    action: str,
    resource_type: str = "",
    resource_id: str = "",
    details: dict[str, Any] | None = None,
) -> None:
    require_permission(
        request=request,
        user=user,
        permission=permission,
        action=action,
        has_permission_fn=has_permission,
        audit_writer=audit_event,
        resource_type=resource_type,
        resource_id=resource_id,
        details=details,
    )


def begin_idempotency(
    request: Request,
    user: CurrentUser,
    *,
    request_scope: str,
    payload: dict[str, Any],
) -> IdempotencyState:
    return begin_kb_idempotency(
        request,
        user,
        request_scope=request_scope,
        payload=payload,
        db=db,
        ttl_hours=IDEMPOTENCY_TTL_HOURS,
        counter=KB_IDEMPOTENCY_TOTAL,
    )


def complete_idempotency(
    state: IdempotencyState,
    user: CurrentUser,
    *,
    response_payload: dict[str, Any],
    resource_id: str = "",
) -> None:
    complete_kb_idempotency(
        state,
        user,
        response_payload=response_payload,
        resource_id=resource_id,
        db=db,
        to_json=to_json,
        counter=KB_IDEMPOTENCY_TOTAL,
    )


def fail_idempotency(state: IdempotencyState, user: CurrentUser, exc: Exception) -> None:
    fail_kb_idempotency(
        state,
        user,
        exc,
        db=db,
        to_json=to_json,
        counter=KB_IDEMPOTENCY_TOTAL,
    )


def list_audit_events(
    *,
    actor_user_id: str = "",
    resource_type: str = "",
    resource_id: str = "",
    action: str = "",
    outcome: str = "",
    created_from: str = "",
    created_to: str = "",
    limit: int,
) -> list[dict[str, Any]]:
    return query_kb_audit_events(
        db=db,
        actor_user_id=actor_user_id,
        resource_type=resource_type,
        resource_id=resource_id,
        action=action,
        outcome=outcome,
        created_from=created_from,
        created_to=created_to,
        limit=limit,
    )


def can_manage_everything(user: CurrentUser) -> bool:
    return can_manage_all_kb(user, has_permission_fn=has_permission, manage_permission=KB_MANAGE_PERMISSION)
