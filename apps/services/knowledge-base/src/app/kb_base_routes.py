from __future__ import annotations

import difflib
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, Query, Request

from shared.api_errors import raise_api_error
from shared.auth import CurrentUser

from .db import to_json
from .kb_api_support import audit_event, require_kb_permission
from .kb_chunk_governance import list_document_chunks
from .kb_resource_store import (
    ensure_base_exists,
    fetch_base_documents,
    load_base,
    load_document,
    load_document_unscoped,
    load_latest_ingest_job_for_document,
    list_document_versions,
    list_document_visual_assets,
    list_visual_storage_keys_for_documents,
    serialize_ingest_job,
)
from .kb_runtime import KB_READ_PERMISSION, KB_WRITE_PERMISSION, db
from .kb_schemas import ALLOWED_DOCUMENT_VERSION_STATUSES, CreateBaseRequest, UpdateBaseRequest, UpdateDocumentRequest
from .kb_upload_store import cleanup_deleted_resources, list_base_upload_sessions, list_document_upload_sessions
from .vector_store import delete_base_vectors, delete_document_vectors


router = APIRouter()


def _ensure_same_version_family(anchor: dict[str, Any], candidate: dict[str, Any]) -> None:
    if str(anchor.get("base_id") or "") != str(candidate.get("base_id") or ""):
        raise_api_error(400, "document_version_cross_base", "documents must belong to the same knowledge base")
    if str(anchor.get("version_family_key") or "") != str(candidate.get("version_family_key") or ""):
        raise_api_error(400, "document_version_family_mismatch", "documents must belong to the same version family")


def _group_document_sections(chunks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    sections: list[dict[str, Any]] = []
    current_key = None
    current_section: dict[str, Any] | None = None
    for chunk in chunks:
        section_key = (int(chunk.get("section_index") or 0), str(chunk.get("section_title") or ""))
        if section_key != current_key:
            current_key = section_key
            current_section = {
                "section_index": section_key[0],
                "section_title": section_key[1],
                "chunks": [],
            }
            sections.append(current_section)
        if current_section is not None:
            current_section["chunks"].append(chunk)
    for section in sections:
        active_chunks = [str(item.get("text_content") or "") for item in section["chunks"] if not bool(item.get("disabled"))]
        section["text_content"] = "\n\n".join(part for part in active_chunks if part.strip()).strip()
    return sections


def _render_document_text(sections: list[dict[str, Any]]) -> str:
    blocks: list[str] = []
    for section in sections:
        title = str(section.get("section_title") or "").strip() or f"Section {int(section.get('section_index') or 0) + 1}"
        body = str(section.get("text_content") or "").strip()
        if body:
            blocks.append(f"## {title}\n{body}")
    return "\n\n".join(blocks).strip()


def _build_version_content_payload(document: dict[str, Any], chunks: list[dict[str, Any]]) -> dict[str, Any]:
    sections = _group_document_sections(chunks)
    return {
        "document_id": str(document.get("id") or ""),
        "file_name": str(document.get("file_name") or ""),
        "version_label": str(document.get("version_label") or ""),
        "version_number": int(document.get("version_number") or 1),
        "version_status": str(document.get("version_status") or ""),
        "is_current_version": bool(document.get("is_current_version")),
        "effective_now": bool(document.get("effective_now")),
        "section_count": len(sections),
        "chunk_count": len(chunks),
        "sections": sections,
        "full_text": _render_document_text(sections),
    }


def _build_version_diff_payload(
    *,
    source_document: dict[str, Any],
    source_chunks: list[dict[str, Any]],
    target_document: dict[str, Any],
    target_chunks: list[dict[str, Any]],
) -> dict[str, Any]:
    source_sections = _group_document_sections(source_chunks)
    target_sections = _group_document_sections(target_chunks)
    source_text = _render_document_text(source_sections)
    target_text = _render_document_text(target_sections)
    source_map = {
        (int(item.get("section_index") or 0), int(item.get("chunk_index") or 0), str(item.get("section_title") or "")): str(item.get("text_content") or "")
        for item in source_chunks
        if not bool(item.get("disabled"))
    }
    target_map = {
        (int(item.get("section_index") or 0), int(item.get("chunk_index") or 0), str(item.get("section_title") or "")): str(item.get("text_content") or "")
        for item in target_chunks
        if not bool(item.get("disabled"))
    }
    source_keys = set(source_map.keys())
    target_keys = set(target_map.keys())
    modified = sorted(key for key in (source_keys & target_keys) if source_map[key] != target_map[key])
    diff_lines = list(
        difflib.unified_diff(
            source_text.splitlines(),
            target_text.splitlines(),
            fromfile=str(source_document.get("version_label") or source_document.get("file_name") or "source"),
            tofile=str(target_document.get("version_label") or target_document.get("file_name") or "target"),
            lineterm="",
        )
    )
    return {
        "source_document_id": str(source_document.get("id") or ""),
        "target_document_id": str(target_document.get("id") or ""),
        "summary": {
            "added_chunks": len(target_keys - source_keys),
            "removed_chunks": len(source_keys - target_keys),
            "modified_chunks": len(modified),
            "changed_sections": len(
                {
                    (key[0], key[2])
                    for key in list(target_keys - source_keys) + list(source_keys - target_keys) + modified
                }
            ),
        },
        "diff_text": "\n".join(diff_lines).strip(),
    }


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


@router.get("/api/v1/kb/documents/{document_id}/versions")
def get_document_versions(document_id: str, request: Request, user: CurrentUser) -> dict[str, Any]:
    require_kb_permission(request, user, KB_READ_PERMISSION, action="kb.document.versions", resource_type="document", resource_id=document_id)
    return {"items": list_document_versions(document_id, user=user)}


@router.get("/api/v1/kb/documents/{document_id}/versions/{version_id}/content")
def get_document_version_content(
    document_id: str,
    version_id: str,
    request: Request,
    user: CurrentUser,
    include_disabled: bool = Query(default=True),
) -> dict[str, Any]:
    require_kb_permission(request, user, KB_READ_PERMISSION, action="kb.document.version_content", resource_type="document", resource_id=document_id)
    anchor = load_document(document_id, user=user, request=request, action="kb.document.version_content")
    version_document = load_document(version_id, user=user, request=request, action="kb.document.version_content")
    _ensure_same_version_family(anchor, version_document)
    chunks = list_document_chunks(version_id, user=user, request=request, include_disabled=include_disabled)
    return {"document": _build_version_content_payload(version_document, chunks)}


@router.get("/api/v1/kb/documents/{document_id}/versions/{version_id}/diff")
def get_document_version_diff(
    document_id: str,
    version_id: str,
    request: Request,
    user: CurrentUser,
    compare_to_document_id: str = Query(default="", max_length=64),
) -> dict[str, Any]:
    require_kb_permission(request, user, KB_READ_PERMISSION, action="kb.document.version_diff", resource_type="document", resource_id=document_id)
    anchor = load_document(document_id, user=user, request=request, action="kb.document.version_diff")
    source_document = load_document(version_id, user=user, request=request, action="kb.document.version_diff")
    target_document = anchor if not compare_to_document_id.strip() else load_document(compare_to_document_id.strip(), user=user, request=request, action="kb.document.version_diff")
    _ensure_same_version_family(anchor, source_document)
    _ensure_same_version_family(anchor, target_document)
    source_chunks = list_document_chunks(str(source_document.get("id") or ""), user=user, request=request, include_disabled=False)
    target_chunks = list_document_chunks(str(target_document.get("id") or ""), user=user, request=request, include_disabled=False)
    return {
        "source": _build_version_content_payload(source_document, source_chunks),
        "target": _build_version_content_payload(target_document, target_chunks),
        "diff": _build_version_diff_payload(
            source_document=source_document,
            source_chunks=source_chunks,
            target_document=target_document,
            target_chunks=target_chunks,
        ),
    }


@router.patch("/api/v1/kb/documents/{document_id}")
def update_document(document_id: str, payload: UpdateDocumentRequest, request: Request, user: CurrentUser) -> dict[str, Any]:
    require_kb_permission(request, user, KB_WRITE_PERMISSION, action="kb.document.update", resource_type="document", resource_id=document_id)
    document = load_document(document_id, user=user, request=request, action="kb.document.update")
    next_file_name = payload.file_name.strip() if payload.file_name is not None else str(document.get("file_name") or "")
    next_category = payload.category.strip() if payload.category is not None else str((document.get("stats_json") or {}).get("category") or "")
    next_family_key = payload.version_family_key if payload.version_family_key is not None else str(document.get("version_family_key") or document_id)
    next_version_label = payload.version_label if payload.version_label is not None else str(document.get("version_label") or "")
    next_version_number = int(payload.version_number if payload.version_number is not None else int(document.get("version_number") or 1))
    next_version_status = payload.version_status if payload.version_status is not None else str(document.get("version_status") or "active")
    next_is_current_version = bool(payload.is_current_version if payload.is_current_version is not None else bool(document.get("is_current_version")))
    next_effective_from = payload.effective_from if payload.effective_from is not None else document.get("effective_from")
    next_effective_to = payload.effective_to if payload.effective_to is not None else document.get("effective_to")
    next_supersedes_document_id = (
        payload.supersedes_document_id
        if payload.supersedes_document_id is not None
        else (str(document.get("supersedes_document_id") or "") or None)
    )
    if next_version_status not in ALLOWED_DOCUMENT_VERSION_STATUSES:
        raise_api_error(400, "document_version_status_invalid", f"unsupported version status: {next_version_status}")
    if next_is_current_version and next_version_status != "active":
        raise_api_error(400, "document_version_current_requires_active", "current version must use active status")
    if next_is_current_version and isinstance(next_effective_from, datetime) and next_effective_from > datetime.now(timezone.utc):
        raise_api_error(400, "document_version_current_future_effective", "future-effective version cannot be marked current yet")
    if isinstance(next_effective_from, datetime) and isinstance(next_effective_to, datetime) and next_effective_to < next_effective_from:
        raise_api_error(400, "document_version_window_invalid", "effective_to must be greater than or equal to effective_from")
    if next_supersedes_document_id == document_id:
        raise_api_error(400, "document_version_supersedes_self", "document cannot supersede itself")
    if next_supersedes_document_id:
        superseded = load_document(next_supersedes_document_id, user=user, request=request, action="kb.document.update")
        if str(superseded.get("base_id") or "") != str(document.get("base_id") or ""):
            raise_api_error(400, "document_version_cross_base", "superseded document must belong to the same knowledge base")
    next_stats = dict(document.get("stats_json") or {})
    next_stats["category"] = next_category
    with db.connect() as conn:
        with conn.cursor() as cur:
            if next_is_current_version:
                cur.execute(
                    """
                    UPDATE kb_documents
                    SET is_current_version = FALSE,
                        version_status = CASE
                            WHEN version_status = 'active' THEN 'superseded'
                            ELSE version_status
                        END,
                        updated_at = NOW()
                    WHERE base_id = %s
                      AND version_family_key = %s
                      AND id <> %s
                      AND is_current_version = TRUE
                    """,
                    (document["base_id"], next_family_key, document_id),
                )
            cur.execute(
                """
                UPDATE kb_documents
                SET file_name = %s,
                    stats_json = %s::jsonb,
                    version_family_key = %s,
                    version_label = %s,
                    version_number = %s,
                    version_status = %s,
                    is_current_version = %s,
                    effective_from = %s,
                    effective_to = %s,
                    supersedes_document_id = %s,
                    updated_at = NOW()
                WHERE id = %s
                """,
                (
                    next_file_name,
                    to_json(next_stats),
                    next_family_key,
                    next_version_label,
                    next_version_number,
                    next_version_status,
                    next_is_current_version,
                    next_effective_from,
                    next_effective_to,
                    next_supersedes_document_id,
                    document_id,
                ),
            )
            cur.execute(
                """
                UPDATE kb_upload_sessions
                SET file_name = %s,
                    category = %s,
                    version_family_key = %s,
                    version_label = %s,
                    version_number = %s,
                    version_status = %s,
                    is_current_version = %s,
                    effective_from = %s,
                    effective_to = %s,
                    supersedes_document_id = %s,
                    updated_at = NOW()
                WHERE document_id = %s OR id = %s
                """,
                (
                    next_file_name,
                    next_category,
                    next_family_key,
                    next_version_label,
                    next_version_number,
                    next_version_status,
                    next_is_current_version,
                    next_effective_from,
                    next_effective_to,
                    next_supersedes_document_id,
                    document_id,
                    document.get("upload_session_id"),
                ),
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
    updated = load_document(document_id, user=user, request=request, action="kb.document.get")
    latest_job = load_latest_ingest_job_for_document(document_id, user=user)
    payload_out = dict(updated)
    payload_out["latest_job"] = serialize_ingest_job(latest_job) if latest_job else None
    return payload_out


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
