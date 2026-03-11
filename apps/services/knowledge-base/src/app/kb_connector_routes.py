from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, Query, Request

from shared.api_errors import raise_api_error
from shared.auth import CurrentUser

from .db import to_json
from .kb_api_support import audit_event, can_manage_everything, require_kb_permission
from .kb_local_sync import execute_local_directory_sync
from .kb_notion_sync import execute_notion_sync
from .kb_resource_store import ensure_base_exists, load_base
from .kb_runtime import KB_READ_PERMISSION, KB_WRITE_PERMISSION, db, logger, storage
from .kb_schemas import CreateConnectorRequest, RunConnectorRequest, UpdateConnectorRequest
from .kb_sql_sync import execute_sql_sync
from .kb_url_sync import execute_url_sync


router = APIRouter()
_CONNECTOR_SCHEDULER_RECONCILE = lambda: None


def _serialize_connector(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(row.get("id") or ""),
        "connector_id": str(row.get("id") or ""),
        "base_id": str(row.get("base_id") or ""),
        "name": str(row.get("name") or ""),
        "connector_type": str(row.get("connector_type") or ""),
        "status": str(row.get("status") or "active"),
        "config": dict(row.get("config_json") or {}),
        "schedule": {
            "enabled": bool(row.get("schedule_enabled")),
            "interval_minutes": int(row["schedule_interval_minutes"]) if row.get("schedule_interval_minutes") is not None else None,
            "last_run_at": row.get("last_run_at"),
            "next_run_at": row.get("next_run_at"),
        },
        "last_result": dict(row.get("last_result_json") or {}),
        "created_by": str(row.get("created_by") or ""),
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
    }


def _serialize_run(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(row.get("id") or ""),
        "run_id": str(row.get("id") or ""),
        "connector_id": str(row.get("connector_id") or ""),
        "base_id": str(row.get("base_id") or ""),
        "connector_type": str(row.get("connector_type") or ""),
        "status": str(row.get("status") or ""),
        "dry_run": bool(row.get("dry_run")),
        "result": dict(row.get("result_json") or {}),
        "error_message": str(row.get("error_message") or ""),
        "started_at": row.get("started_at"),
        "finished_at": row.get("finished_at"),
        "created_by": str(row.get("created_by") or ""),
    }


def _next_run_at(*, enabled: bool, interval_minutes: int | None) -> datetime | None:
    if not enabled or interval_minutes is None:
        return None
    return datetime.now(timezone.utc) + timedelta(minutes=int(interval_minutes))


def _schedule_payload(schedule: Any) -> tuple[bool, int | None, datetime | None]:
    enabled = bool(getattr(schedule, "enabled", False))
    interval_minutes = int(getattr(schedule, "interval_minutes", 0) or 0) or None
    return enabled, interval_minutes, (datetime.now(timezone.utc) if enabled and interval_minutes is not None else None)


def set_connector_scheduler_reconciler(callback) -> None:
    global _CONNECTOR_SCHEDULER_RECONCILE
    _CONNECTOR_SCHEDULER_RECONCILE = callback or (lambda: None)


def _notify_connector_scheduler() -> None:
    try:
        _CONNECTOR_SCHEDULER_RECONCILE()
    except Exception:
        logger.exception("kb connector scheduler reconcile callback failed")


def has_active_scheduled_connectors() -> bool:
    with db.connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT COUNT(*) AS total_count
                FROM kb_connectors
                WHERE status = 'active'
                  AND schedule_enabled = TRUE
                """
            )
            row = cur.fetchone() or {}
    return int(row.get("total_count") or 0) > 0


def _load_connector(connector_id: str, *, user: CurrentUser, request: Request | None = None, action: str = "kb.connector.get") -> dict[str, Any]:
    with db.connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT connectors.*, bases.created_by AS base_created_by
                FROM kb_connectors connectors
                JOIN kb_bases bases ON bases.id = connectors.base_id
                WHERE connectors.id = %s
                """,
                (connector_id,),
            )
            row = cur.fetchone()
    if row is None:
        raise_api_error(404, "connector_not_found", "connector not found")
    if str(row.get("created_by") or "") != user.user_id and str(row.get("base_created_by") or "") != user.user_id and not can_manage_everything(user):
        if request is not None:
            audit_event(
                action=action,
                outcome="denied",
                request=request,
                user=user,
                resource_type="connector",
                resource_id=connector_id,
                scope="owner",
            )
        raise_api_error(403, "permission_denied", "connector is outside your scope")
    return row


def _execute_connector(connector: dict[str, Any], *, user: CurrentUser, dry_run: bool) -> dict[str, Any]:
    config = dict(connector.get("config_json") or {})
    connector_type = str(connector.get("connector_type") or "")
    base_id = str(connector.get("base_id") or "")
    common_kwargs = {
        "base_id": base_id,
        "category": str(config.get("category") or ""),
        "delete_missing": bool(config.get("delete_missing", True)),
        "dry_run": dry_run,
        "user": user,
        "db": db,
        "storage": storage,
    }
    if connector_type == "local_directory":
        return execute_local_directory_sync(
            source_path=str(config.get("source_path") or ""),
            recursive=bool(config.get("recursive", True)),
            max_files=int(config["max_files"]) if config.get("max_files") is not None else None,
            **common_kwargs,
        )
    if connector_type == "notion":
        return execute_notion_sync(
            page_ids=list(config.get("page_ids") or []),
            max_pages=int(config["max_pages"]) if config.get("max_pages") is not None else None,
            **common_kwargs,
        )
    if connector_type in {"web_crawler", "feishu_document", "dingtalk_document"}:
        return execute_url_sync(
            connector_type=connector_type,
            urls=list(config.get("urls") or []),
            max_urls=int(config["max_urls"]) if config.get("max_urls") is not None else None,
            header_name=str(config.get("header_name") or ""),
            header_value_env=str(config.get("header_value_env") or ""),
            **common_kwargs,
        )
    if connector_type == "sql_query":
        return execute_sql_sync(
            dsn_env=str(config.get("dsn_env") or ""),
            query=str(config.get("query") or ""),
            id_column=str(config.get("id_column") or "id"),
            text_column=str(config.get("text_column") or "content"),
            title_column=str(config.get("title_column") or config.get("id_column") or "id"),
            updated_at_column=str(config.get("updated_at_column") or ""),
            max_rows=int(config["max_rows"]) if config.get("max_rows") is not None else None,
            **common_kwargs,
        )
    raise_api_error(400, "connector_type_unsupported", f"unsupported connector type: {connector_type}")


def _create_run_record(connector: dict[str, Any], *, user: CurrentUser, dry_run: bool) -> str:
    run_id = str(uuid4())
    with db.connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO kb_connector_runs (
                    id, connector_id, base_id, connector_type, status, dry_run, created_by
                )
                VALUES (%s, %s, %s, %s, 'running', %s, %s)
                """,
                (
                    run_id,
                    connector.get("id"),
                    connector.get("base_id"),
                    connector.get("connector_type"),
                    dry_run,
                    user.user_id,
                ),
            )
        conn.commit()
    return run_id


def _finish_run_record(run_id: str, *, connector: dict[str, Any], result: dict[str, Any] | None, error_message: str = "") -> None:
    successful = not error_message
    enabled = bool(connector.get("schedule_enabled"))
    interval_minutes = int(connector.get("schedule_interval_minutes") or 0) or None
    with db.connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE kb_connector_runs
                SET status = %s,
                    result_json = %s::jsonb,
                    error_message = %s,
                    finished_at = NOW()
                WHERE id = %s
                """,
                ("done" if successful else "failed", to_json(result or {}), error_message, run_id),
            )
            cur.execute(
                """
                UPDATE kb_connectors
                SET last_result_json = %s::jsonb,
                    last_run_at = NOW(),
                    next_run_at = %s,
                    updated_at = NOW()
                WHERE id = %s
                """,
                (
                    to_json(result or {"error_message": error_message}),
                    _next_run_at(enabled=enabled, interval_minutes=interval_minutes),
                    connector.get("id"),
                ),
            )
        conn.commit()
    _notify_connector_scheduler()


@router.get("/api/v1/kb/connectors")
def list_connectors(
    request: Request,
    user: CurrentUser,
    base_id: str = Query(default="", max_length=128),
) -> dict[str, Any]:
    require_kb_permission(request, user, KB_READ_PERMISSION, action="kb.connector.list", resource_type="connector")
    clauses = ["TRUE"]
    params: list[Any] = []
    if base_id.strip():
        ensure_base_exists(base_id.strip(), user=user, request=request, action="kb.connector.list")
        clauses.append("connectors.base_id = %s")
        params.append(base_id.strip())
    if not can_manage_everything(user):
        clauses.append("(connectors.created_by = %s OR bases.created_by = %s)")
        params.extend([user.user_id, user.user_id])
    with db.connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT connectors.*, bases.created_by AS base_created_by
                FROM kb_connectors connectors
                JOIN kb_bases bases ON bases.id = connectors.base_id
                WHERE {" AND ".join(clauses)}
                ORDER BY connectors.updated_at DESC
                """,
                tuple(params),
            )
            rows = cur.fetchall()
    return {"items": [_serialize_connector(row) for row in rows]}


@router.post("/api/v1/kb/connectors")
def create_connector(payload: CreateConnectorRequest, request: Request, user: CurrentUser) -> dict[str, Any]:
    require_kb_permission(
        request,
        user,
        KB_WRITE_PERMISSION,
        action="kb.connector.create",
        resource_type="knowledge_base",
        resource_id=payload.base_id,
    )
    load_base(payload.base_id, user=user, request=request, action="kb.connector.create")
    connector_id = str(uuid4())
    schedule_enabled, schedule_interval_minutes, next_run_at = _schedule_payload(payload.schedule)
    with db.connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO kb_connectors (
                    id, base_id, name, connector_type, status, config_json,
                    schedule_enabled, schedule_interval_minutes, next_run_at, created_by
                )
                VALUES (%s, %s, %s, %s, 'active', %s::jsonb, %s, %s, %s, %s)
                """,
                (
                    connector_id,
                    payload.base_id,
                    payload.name,
                    payload.connector_type,
                    to_json(payload.config),
                    schedule_enabled,
                    schedule_interval_minutes,
                    next_run_at,
                    user.user_id,
                ),
            )
        conn.commit()
    _notify_connector_scheduler()
    connector = _load_connector(connector_id, user=user, request=request, action="kb.connector.get")
    audit_event(
        action="kb.connector.create",
        outcome="success",
        request=request,
        user=user,
        resource_type="connector",
        resource_id=connector_id,
        scope="owner",
        details={"base_id": payload.base_id, "connector_type": payload.connector_type},
    )
    return _serialize_connector(connector)


@router.get("/api/v1/kb/connectors/{connector_id}")
def get_connector(connector_id: str, request: Request, user: CurrentUser) -> dict[str, Any]:
    require_kb_permission(request, user, KB_READ_PERMISSION, action="kb.connector.get", resource_type="connector", resource_id=connector_id)
    return _serialize_connector(_load_connector(connector_id, user=user, request=request, action="kb.connector.get"))


@router.patch("/api/v1/kb/connectors/{connector_id}")
def update_connector(connector_id: str, payload: UpdateConnectorRequest, request: Request, user: CurrentUser) -> dict[str, Any]:
    require_kb_permission(request, user, KB_WRITE_PERMISSION, action="kb.connector.update", resource_type="connector", resource_id=connector_id)
    current = _load_connector(connector_id, user=user, request=request, action="kb.connector.update")
    next_name = payload.name if payload.name is not None else str(current.get("name") or "")
    next_config = payload.config if payload.config is not None else dict(current.get("config_json") or {})
    if payload.schedule is None:
        next_schedule_enabled = bool(current.get("schedule_enabled"))
        next_schedule_interval = int(current.get("schedule_interval_minutes") or 0) or None
        next_run_at = current.get("next_run_at")
    else:
        next_schedule_enabled, next_schedule_interval, next_run_at = _schedule_payload(payload.schedule)
    next_status = payload.status if payload.status is not None else str(current.get("status") or "active")
    with db.connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE kb_connectors
                SET name = %s,
                    config_json = %s::jsonb,
                    status = %s,
                    schedule_enabled = %s,
                    schedule_interval_minutes = %s,
                    next_run_at = %s,
                    updated_at = NOW()
                WHERE id = %s
                """,
                (
                    next_name,
                    to_json(next_config),
                    next_status,
                    next_schedule_enabled,
                    next_schedule_interval,
                    next_run_at,
                    connector_id,
                ),
            )
        conn.commit()
    _notify_connector_scheduler()
    audit_event(
        action="kb.connector.update",
        outcome="success",
        request=request,
        user=user,
        resource_type="connector",
        resource_id=connector_id,
        scope="owner" if str(current.get("created_by") or "") == user.user_id else "managed",
    )
    return _serialize_connector(_load_connector(connector_id, user=user, request=request, action="kb.connector.get"))


@router.delete("/api/v1/kb/connectors/{connector_id}")
def delete_connector(connector_id: str, request: Request, user: CurrentUser) -> dict[str, Any]:
    require_kb_permission(request, user, KB_WRITE_PERMISSION, action="kb.connector.delete", resource_type="connector", resource_id=connector_id)
    current = _load_connector(connector_id, user=user, request=request, action="kb.connector.delete")
    with db.connect() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM kb_connectors WHERE id = %s", (connector_id,))
        conn.commit()
    _notify_connector_scheduler()
    audit_event(
        action="kb.connector.delete",
        outcome="success",
        request=request,
        user=user,
        resource_type="connector",
        resource_id=connector_id,
        scope="owner" if str(current.get("created_by") or "") == user.user_id else "managed",
    )
    return {"deleted": True, "connector_id": connector_id}


@router.get("/api/v1/kb/connectors/{connector_id}/runs")
def list_connector_runs(connector_id: str, request: Request, user: CurrentUser) -> dict[str, Any]:
    require_kb_permission(request, user, KB_READ_PERMISSION, action="kb.connector.run.list", resource_type="connector", resource_id=connector_id)
    _load_connector(connector_id, user=user, request=request, action="kb.connector.run.list")
    with db.connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT *
                FROM kb_connector_runs
                WHERE connector_id = %s
                ORDER BY started_at DESC
                LIMIT 50
                """,
                (connector_id,),
            )
            rows = cur.fetchall()
    return {"items": [_serialize_run(row) for row in rows]}


@router.post("/api/v1/kb/connectors/{connector_id}/sync")
def run_connector(connector_id: str, payload: RunConnectorRequest, request: Request, user: CurrentUser) -> dict[str, Any]:
    require_kb_permission(request, user, KB_WRITE_PERMISSION, action="kb.connector.sync", resource_type="connector", resource_id=connector_id)
    connector = _load_connector(connector_id, user=user, request=request, action="kb.connector.sync")
    run_id = _create_run_record(connector, user=user, dry_run=payload.dry_run)
    try:
        result = _execute_connector(connector, user=user, dry_run=payload.dry_run)
    except Exception as exc:
        _finish_run_record(run_id, connector=connector, result=None, error_message=str(exc))
        audit_event(
            action="kb.connector.sync",
            outcome="failed",
            request=request,
            user=user,
            resource_type="connector",
            resource_id=connector_id,
            scope="owner" if str(connector.get("created_by") or "") == user.user_id else "managed",
            details={"run_id": run_id, "error_type": exc.__class__.__name__},
        )
        raise
    _finish_run_record(run_id, connector=connector, result=result)
    audit_event(
        action="kb.connector.sync",
        outcome="success",
        request=request,
        user=user,
        resource_type="connector",
        resource_id=connector_id,
        scope="owner" if str(connector.get("created_by") or "") == user.user_id else "managed",
        details={"run_id": run_id, "dry_run": payload.dry_run},
    )
    with db.connect() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM kb_connector_runs WHERE id = %s", (run_id,))
            run_row = cur.fetchone()
    return {"run": _serialize_run(run_row or {}), "result": result}


@router.post("/api/v1/kb/connectors/run-due")
def run_due_connectors(payload: RunConnectorRequest, request: Request, user: CurrentUser) -> dict[str, Any]:
    require_kb_permission(request, user, KB_WRITE_PERMISSION, action="kb.connector.run_due", resource_type="connector")
    result = run_due_connectors_batch(limit=int(payload.limit or 10), dry_run=payload.dry_run, user=user)
    audit_event(
        action="kb.connector.run_due",
        outcome="success",
        request=request,
        user=user,
        resource_type="connector",
        resource_id="",
        scope="owner",
        details={"connector_count": len(result.get("items") or []), "dry_run": payload.dry_run},
    )
    return result


def run_due_connectors_batch(*, limit: int, dry_run: bool, user: CurrentUser) -> dict[str, Any]:
    limit = int(limit or 10)
    clauses = [
        "status = 'active'",
        "schedule_enabled = TRUE",
        "next_run_at IS NOT NULL",
        "next_run_at <= NOW()",
    ]
    params: list[Any] = []
    if not can_manage_everything(user):
        clauses.append("created_by = %s")
        params.append(user.user_id)
    params.append(limit)
    with db.connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT *
                FROM kb_connectors
                WHERE {" AND ".join(clauses)}
                ORDER BY next_run_at ASC
                LIMIT %s
                """,
                tuple(params),
            )
            connectors = cur.fetchall()
    results = []
    for connector in connectors:
        run_id = _create_run_record(connector, user=user, dry_run=dry_run)
        try:
            result = _execute_connector(connector, user=user, dry_run=dry_run)
        except Exception as exc:
            _finish_run_record(run_id, connector=connector, result=None, error_message=str(exc))
            results.append({"connector_id": str(connector.get("id") or ""), "run_id": run_id, "status": "failed", "error": str(exc)})
            continue
        _finish_run_record(run_id, connector=connector, result=result)
        results.append({"connector_id": str(connector.get("id") or ""), "run_id": run_id, "status": "done", "result": result})
    return {"items": results, "count": len(results)}
