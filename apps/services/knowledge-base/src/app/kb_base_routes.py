from __future__ import annotations

from typing import Any
from uuid import uuid4

from fastapi import APIRouter, Request

from shared.auth import CurrentUser

from .db import to_json
from .kb_api_support import audit_event, require_kb_permission
from .kb_resource_store import (
    ensure_base_exists,
    fetch_base_documents,
    load_base,
    load_document,
    load_latest_ingest_job_for_document,
    list_document_visual_assets,
    list_visual_storage_keys_for_documents,
    serialize_ingest_job,
)
from .kb_runtime import KB_READ_PERMISSION, KB_WRITE_PERMISSION, db
from .kb_schemas import CreateBaseRequest, UpdateBaseRequest, UpdateDocumentRequest
from .kb_upload_store import cleanup_deleted_resources, list_base_upload_sessions, list_document_upload_sessions
from .vector_store import delete_base_vectors, delete_document_vectors


router = APIRouter()


@router.post("/api/v1/kb/bases")
def create_base(payload: CreateBaseRequest, request: Request, user: CurrentUser) -> dict[str, Any]:
    require_kb_permission(request, user, KB_WRITE_PERMISSION, action="kb.base.create", resource_type="knowledge_base")
    base_id = str(uuid4())
    with db.connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO kb_bases (id, name, description, category, created_by)
                VALUES (%s, %s, %s, %s, %s)
                """,
                (base_id, payload.name.strip(), payload.description.strip(), payload.category.strip(), user.user_id),
            )
        conn.commit()
    audit_event(
        action="kb.base.create",
        outcome="success",
        request=request,
        user=user,
        resource_type="knowledge_base",
        resource_id=base_id,
        scope="owner",
    )
    return {"id": base_id, "name": payload.name.strip(), "description": payload.description.strip(), "category": payload.category.strip()}


@router.get("/api/v1/kb/bases")
def list_bases(request: Request, user: CurrentUser) -> dict[str, Any]:
    from .kb_api_support import can_manage_everything

    require_kb_permission(request, user, KB_READ_PERMISSION, action="kb.base.list", resource_type="knowledge_base")
    with db.connect() as conn:
        with conn.cursor() as cur:
            if can_manage_everything(user):
                cur.execute("SELECT * FROM kb_bases ORDER BY created_at DESC")
            else:
                cur.execute(
                    """
                    SELECT *
                    FROM kb_bases
                    WHERE created_by = %s
                    ORDER BY created_at DESC
                    """,
                    (user.user_id,),
                )
            rows = cur.fetchall()
    return {"items": rows}


@router.get("/api/v1/kb/bases/{base_id}")
def get_base(base_id: str, request: Request, user: CurrentUser) -> dict[str, Any]:
    require_kb_permission(request, user, KB_READ_PERMISSION, action="kb.base.get", resource_type="knowledge_base", resource_id=base_id)
    return load_base(base_id, user=user, request=request, action="kb.base.get")


@router.patch("/api/v1/kb/bases/{base_id}")
def update_base(base_id: str, payload: UpdateBaseRequest, request: Request, user: CurrentUser) -> dict[str, Any]:
    require_kb_permission(request, user, KB_WRITE_PERMISSION, action="kb.base.update", resource_type="knowledge_base", resource_id=base_id)
    current = load_base(base_id, user=user, request=request, action="kb.base.update")
    next_name = payload.name.strip() if payload.name is not None else str(current.get("name") or "")
    next_description = payload.description.strip() if payload.description is not None else str(current.get("description") or "")
    next_category = payload.category.strip() if payload.category is not None else str(current.get("category") or "")
    with db.connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE kb_bases
                SET name = %s,
                    description = %s,
                    category = %s
                WHERE id = %s
                """,
                (next_name, next_description, next_category, base_id),
            )
        conn.commit()
    audit_event(
        action="kb.base.update",
        outcome="success",
        request=request,
        user=user,
        resource_type="knowledge_base",
        resource_id=base_id,
        scope="owner" if str(current.get("created_by") or "") == user.user_id else "managed",
    )
    return load_base(base_id, user=user, request=request, action="kb.base.get")


@router.delete("/api/v1/kb/bases/{base_id}")
def delete_base(base_id: str, request: Request, user: CurrentUser) -> dict[str, Any]:
    require_kb_permission(request, user, KB_WRITE_PERMISSION, action="kb.base.delete", resource_type="knowledge_base", resource_id=base_id)
    current = load_base(base_id, user=user, request=request, action="kb.base.delete")
    with db.connect() as conn:
        with conn.cursor() as cur:
            documents = fetch_base_documents(base_id, user=user, cur=cur)
            upload_sessions = list_base_upload_sessions(base_id, user=user, cur=cur)
            visual_storage_keys = list_visual_storage_keys_for_documents([str(item["id"]) for item in documents], cur=cur)
            cur.execute("DELETE FROM kb_bases WHERE id = %s", (base_id,))
        conn.commit()
    cleanup_deleted_resources(
        upload_sessions=upload_sessions,
        storage_keys=[str(item.get("storage_key") or "") for item in documents] + visual_storage_keys,
    )
    delete_base_vectors(base_id)
    audit_event(
        action="kb.base.delete",
        outcome="success",
        request=request,
        user=user,
        resource_type="knowledge_base",
        resource_id=base_id,
        scope="owner" if str(current.get("created_by") or "") == user.user_id else "managed",
        details={"document_count": len(documents)},
    )
    return {"deleted": True, "base_id": base_id}


@router.get("/api/v1/kb/bases/{base_id}/documents")
def list_base_documents(base_id: str, request: Request, user: CurrentUser) -> dict[str, Any]:
    require_kb_permission(request, user, KB_READ_PERMISSION, action="kb.document.list", resource_type="knowledge_base", resource_id=base_id)
    ensure_base_exists(base_id, user=user, request=request, action="kb.document.list")
    return {"items": fetch_base_documents(base_id, user=user)}


@router.get("/api/v1/kb/documents/{document_id}")
def get_document(document_id: str, request: Request, user: CurrentUser) -> dict[str, Any]:
    require_kb_permission(request, user, KB_READ_PERMISSION, action="kb.document.get", resource_type="document", resource_id=document_id)
    document = load_document(document_id, user=user, request=request, action="kb.document.get")
    latest_job = load_latest_ingest_job_for_document(document_id, user=user)
    payload = dict(document)
    payload["latest_job"] = serialize_ingest_job(latest_job) if latest_job else None
    return payload


@router.patch("/api/v1/kb/documents/{document_id}")
def update_document(document_id: str, payload: UpdateDocumentRequest, request: Request, user: CurrentUser) -> dict[str, Any]:
    require_kb_permission(request, user, KB_WRITE_PERMISSION, action="kb.document.update", resource_type="document", resource_id=document_id)
    document = load_document(document_id, user=user, request=request, action="kb.document.update")
    next_file_name = payload.file_name.strip() if payload.file_name is not None else str(document.get("file_name") or "")
    next_category = payload.category.strip() if payload.category is not None else str((document.get("stats_json") or {}).get("category") or "")
    next_stats = dict(document.get("stats_json") or {})
    next_stats["category"] = next_category
    with db.connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE kb_documents
                SET file_name = %s,
                    stats_json = %s::jsonb,
                    updated_at = NOW()
                WHERE id = %s
                """,
                (next_file_name, to_json(next_stats), document_id),
            )
            cur.execute(
                """
                UPDATE kb_upload_sessions
                SET file_name = %s,
                    category = %s,
                    updated_at = NOW()
                WHERE document_id = %s OR id = %s
                """,
                (next_file_name, next_category, document_id, document.get("upload_session_id")),
            )
        conn.commit()
    audit_event(
        action="kb.document.update",
        outcome="success",
        request=request,
        user=user,
        resource_type="document",
        resource_id=document_id,
        scope="owner" if str(document.get("created_by") or "") == user.user_id else "managed",
    )
    return load_document(document_id, user=user, request=request, action="kb.document.get")


@router.delete("/api/v1/kb/documents/{document_id}")
def delete_document(document_id: str, request: Request, user: CurrentUser) -> dict[str, Any]:
    require_kb_permission(request, user, KB_WRITE_PERMISSION, action="kb.document.delete", resource_type="document", resource_id=document_id)
    document = load_document(document_id, user=user, request=request, action="kb.document.delete")
    with db.connect() as conn:
        with conn.cursor() as cur:
            upload_sessions = list_document_upload_sessions(document_id, document.get("upload_session_id"), user=user, cur=cur)
            visual_storage_keys = list_visual_storage_keys_for_documents([document_id], cur=cur)
            for session in upload_sessions:
                cur.execute("DELETE FROM kb_upload_sessions WHERE id = %s", (session["id"],))
            cur.execute("DELETE FROM kb_documents WHERE id = %s", (document_id,))
        conn.commit()
    cleanup_deleted_resources(
        upload_sessions=upload_sessions,
        storage_keys=[str(document.get("storage_key") or "")] + visual_storage_keys,
    )
    delete_document_vectors(document_id)
    audit_event(
        action="kb.document.delete",
        outcome="success",
        request=request,
        user=user,
        resource_type="document",
        resource_id=document_id,
        scope="owner" if str(document.get("created_by") or "") == user.user_id else "managed",
    )
    return {"deleted": True, "document_id": document_id, "base_id": str(document.get("base_id") or "")}


@router.get("/api/v1/kb/documents/{document_id}/events")
def get_document_events(document_id: str, request: Request, user: CurrentUser) -> dict[str, Any]:
    require_kb_permission(request, user, KB_READ_PERMISSION, action="kb.document.events", resource_type="document", resource_id=document_id)
    load_document(document_id, user=user, request=request, action="kb.document.events")
    with db.connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT *
                FROM kb_document_events
                WHERE document_id = %s
                ORDER BY created_at DESC
                """,
                (document_id,),
            )
            rows = cur.fetchall()
    return {"items": rows}


@router.get("/api/v1/kb/documents/{document_id}/visual-assets")
def get_document_visual_assets(document_id: str, request: Request, user: CurrentUser) -> dict[str, Any]:
    require_kb_permission(request, user, KB_READ_PERMISSION, action="kb.document.visual_assets", resource_type="document", resource_id=document_id)
    return {"items": list_document_visual_assets(document_id, user=user)}
