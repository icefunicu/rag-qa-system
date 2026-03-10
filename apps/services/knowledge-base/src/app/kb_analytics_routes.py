from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request

from shared.auth import CurrentUser

from .kb_api_support import audit_event, can_manage_everything, require_kb_permission
from .kb_runtime import KB_READ_PERMISSION, db
from .kb_schemas import KBAnalyticsDashboardResponse


router = APIRouter()
STALLED_THRESHOLD_HOURS = 24


def _scope_clause(user: CurrentUser, view: str, *, field_name: str = "created_by") -> tuple[str, tuple[Any, ...]]:
    if view == "personal":
        return f"{field_name} = %s", (user.user_id,)
    if not can_manage_everything(user):
        raise HTTPException(status_code=403, detail={"detail": "admin dashboard requires kb.manage or platform_admin", "code": "permission_denied"})
    return "TRUE", ()


def _distribution_rows(rows: list[dict[str, Any]], *, key_field: str = "key") -> list[dict[str, Any]]:
    return [
        {
            "key": str(row.get(key_field) or ""),
            "count": int(row.get("total_count") or 0),
        }
        for row in rows
    ]


def _funnel_stats(user: CurrentUser, *, view: str, days: int) -> dict[str, int]:
    base_clause, base_params = _scope_clause(user, view, field_name="created_by")
    document_clause, document_params = _scope_clause(user, view, field_name="created_by")
    with db.connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT COUNT(*) AS total_count
                FROM kb_bases
                WHERE {base_clause}
                  AND created_at >= NOW() - (%s || ' days')::interval
                """,
                base_params + (days,),
            )
            base_row = cur.fetchone() or {}
            cur.execute(
                f"""
                SELECT COUNT(*) AS uploaded_count
                FROM kb_documents
                WHERE {document_clause}
                  AND created_at >= NOW() - (%s || ' days')::interval
                """,
                document_params + (days,),
            )
            uploaded_row = cur.fetchone() or {}
            cur.execute(
                f"""
                SELECT COUNT(*) AS ready_count
                FROM kb_documents
                WHERE {document_clause}
                  AND ready_at IS NOT NULL
                  AND ready_at >= NOW() - (%s || ' days')::interval
                """,
                document_params + (days,),
            )
            ready_row = cur.fetchone() or {}
    return {
        "knowledge_bases_created": int(base_row.get("total_count") or 0),
        "documents_uploaded": int(uploaded_row.get("uploaded_count") or 0),
        "documents_ready": int(ready_row.get("ready_count") or 0),
    }


def _document_status_distribution(user: CurrentUser, *, view: str) -> list[dict[str, Any]]:
    clause, params = _scope_clause(user, view)
    with db.connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT
                    COALESCE(NULLIF(status, ''), 'unknown') AS key,
                    COUNT(*) AS total_count
                FROM kb_documents
                WHERE {clause}
                GROUP BY key
                ORDER BY total_count DESC, key ASC
                """,
                params,
            )
            rows = cur.fetchall()
    return _distribution_rows(rows)


def _enhancement_status_distribution(user: CurrentUser, *, view: str) -> list[dict[str, Any]]:
    clause, params = _scope_clause(user, view)
    with db.connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT
                    COALESCE(NULLIF(enhancement_status, ''), 'none') AS key,
                    COUNT(*) AS total_count
                FROM kb_documents
                WHERE {clause}
                GROUP BY key
                ORDER BY total_count DESC, key ASC
                """,
                params,
            )
            rows = cur.fetchall()
    return _distribution_rows(rows)


def _latest_job_status_distribution(user: CurrentUser, *, view: str) -> list[dict[str, Any]]:
    clause, params = _scope_clause(user, view)
    with db.connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                WITH scoped_docs AS (
                    SELECT id
                    FROM kb_documents
                    WHERE {clause}
                ),
                latest_jobs AS (
                    SELECT DISTINCT ON (jobs.document_id)
                        jobs.document_id,
                        jobs.status
                    FROM kb_ingest_jobs jobs
                    JOIN scoped_docs docs ON docs.id = jobs.document_id
                    ORDER BY jobs.document_id ASC, jobs.created_at DESC
                )
                SELECT
                    COALESCE(NULLIF(status, ''), 'missing') AS key,
                    COUNT(*) AS total_count
                FROM latest_jobs
                GROUP BY key
                ORDER BY total_count DESC, key ASC
                """,
                params,
            )
            rows = cur.fetchall()
    return _distribution_rows(rows)


def _upload_to_ready_latency(user: CurrentUser, *, view: str, days: int) -> dict[str, Any]:
    clause, params = _scope_clause(user, view)
    with db.connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT
                    COUNT(*) AS sample_count,
                    AVG(EXTRACT(EPOCH FROM (ready_at - created_at)) * 1000.0) AS avg_ms,
                    PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY EXTRACT(EPOCH FROM (ready_at - created_at)) * 1000.0) AS p50_ms,
                    PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY EXTRACT(EPOCH FROM (ready_at - created_at)) * 1000.0) AS p95_ms,
                    MAX(EXTRACT(EPOCH FROM (ready_at - created_at)) * 1000.0) AS max_ms
                FROM kb_documents
                WHERE {clause}
                  AND ready_at IS NOT NULL
                  AND ready_at >= NOW() - (%s || ' days')::interval
                  AND ready_at >= created_at
                """,
                params + (days,),
            )
            row = cur.fetchone() or {}
    return {
        "count": int(row.get("sample_count") or 0),
        "avg_ms": round(float(row.get("avg_ms") or 0.0), 3) if row.get("avg_ms") is not None else None,
        "p50_ms": round(float(row.get("p50_ms") or 0.0), 3) if row.get("p50_ms") is not None else None,
        "p95_ms": round(float(row.get("p95_ms") or 0.0), 3) if row.get("p95_ms") is not None else None,
        "max_ms": round(float(row.get("max_ms") or 0.0), 3) if row.get("max_ms") is not None else None,
        "unsupported": False,
    }


def _ingest_summary(user: CurrentUser, *, view: str) -> dict[str, Any]:
    clause, params = _scope_clause(user, view)
    with db.connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                WITH scoped_docs AS (
                    SELECT id, status, query_ready, updated_at
                    FROM kb_documents
                    WHERE {clause}
                ),
                latest_jobs AS (
                    SELECT DISTINCT ON (jobs.document_id)
                        jobs.document_id,
                        jobs.status AS job_status,
                        jobs.updated_at AS job_updated_at
                    FROM kb_ingest_jobs jobs
                    JOIN scoped_docs docs ON docs.id = jobs.document_id
                    ORDER BY jobs.document_id ASC, jobs.created_at DESC
                )
                SELECT
                    COUNT(*) AS total_documents,
                    COUNT(*) FILTER (WHERE docs.status = 'ready') AS ready_documents,
                    COUNT(*) FILTER (WHERE docs.query_ready = TRUE) AS queryable_documents,
                    COUNT(*) FILTER (WHERE docs.status = 'failed') AS failed_documents,
                    COUNT(*) FILTER (WHERE docs.status <> 'ready') AS unfinished_documents,
                    COUNT(*) FILTER (
                        WHERE docs.status NOT IN ('ready', 'failed')
                          AND COALESCE(latest_jobs.job_updated_at, docs.updated_at) <= NOW() - (%s || ' hours')::interval
                    ) AS stalled_documents,
                    COUNT(*) FILTER (WHERE latest_jobs.job_status = 'dead_letter') AS dead_letter_documents,
                    COUNT(*) FILTER (WHERE latest_jobs.job_status IN ('queued', 'retry', 'processing')) AS in_progress_documents
                FROM scoped_docs docs
                LEFT JOIN latest_jobs ON latest_jobs.document_id = docs.id
                """,
                params + (STALLED_THRESHOLD_HOURS,),
            )
            row = cur.fetchone() or {}
    return {
        "total_documents": int(row.get("total_documents") or 0),
        "ready_documents": int(row.get("ready_documents") or 0),
        "queryable_documents": int(row.get("queryable_documents") or 0),
        "failed_documents": int(row.get("failed_documents") or 0),
        "unfinished_documents": int(row.get("unfinished_documents") or 0),
        "stalled_documents": int(row.get("stalled_documents") or 0),
        "dead_letter_documents": int(row.get("dead_letter_documents") or 0),
        "in_progress_documents": int(row.get("in_progress_documents") or 0),
        "stalled_threshold_hours": STALLED_THRESHOLD_HOURS,
    }


def _dashboard_payload(user: CurrentUser, *, view: str, days: int) -> dict[str, Any]:
    return {
        "view": view,
        "days": days,
        "funnel": _funnel_stats(user, view=view, days=days),
        "ingest_health": {
            "summary": _ingest_summary(user, view=view),
            "document_status_distribution": _document_status_distribution(user, view=view),
            "latest_job_status_distribution": _latest_job_status_distribution(user, view=view),
            "enhancement_status_distribution": _enhancement_status_distribution(user, view=view),
            "upload_to_ready_latency_ms": _upload_to_ready_latency(user, view=view, days=days),
        },
        "data_quality": {
            "unsupported_fields": [],
            "degraded_sections": [],
        },
    }


@router.get(
    "/api/v1/kb/analytics/dashboard",
    response_model=KBAnalyticsDashboardResponse,
    summary="知识库主链路分析看板",
    description="返回知识库创建、文档上传、文档 ready 漏斗与 ingest 健康度聚合结果，供 gateway dashboard 复用或前端直接消费。",
)
def get_kb_dashboard(
    request: Request,
    user: CurrentUser,
    view: str = Query(default="personal", max_length=16, description="personal 仅统计当前用户资源；admin 统计管理范围内全部资源。"),
    days: int = Query(default=14, ge=1, le=90, description="漏斗与 ready 耗时统计的滚动时间窗口，单位为天。"),
) -> dict[str, Any]:
    require_kb_permission(request, user, KB_READ_PERMISSION, action="kb.analytics.dashboard.get", resource_type="kb_analytics_dashboard")
    normalized_view = view.strip().lower() or "personal"
    if normalized_view not in {"personal", "admin"}:
        raise HTTPException(status_code=400, detail={"detail": "unsupported analytics view", "code": "analytics_view_invalid"})
    payload = _dashboard_payload(user, view=normalized_view, days=days)
    audit_event(
        action="kb.analytics.dashboard.get",
        outcome="success",
        request=request,
        user=user,
        resource_type="kb_analytics_dashboard",
        scope="admin" if normalized_view == "admin" else "owner",
        details={"view": normalized_view, "days": days},
    )
    return payload
