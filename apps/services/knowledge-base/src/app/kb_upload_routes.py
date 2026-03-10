from __future__ import annotations
from uuid import uuid4

from fastapi import APIRouter, Request

from shared.api_errors import raise_api_error
from shared.auth import CurrentUser

from .db import to_json
from .kb_api_support import audit_event, begin_idempotency, complete_idempotency, fail_idempotency, require_kb_permission
from .kb_resource_store import ensure_base_exists
from .kb_runtime import (
    DEFAULT_INGEST_MAX_ATTEMPTS,
    KB_READ_PERMISSION,
    KB_UPLOAD_REQUESTS_TOTAL,
    KB_WRITE_PERMISSION,
    UPLOAD_PART_EXPIRES_SECONDS,
    db,
    storage,
)
from .kb_schemas import ALLOWED_KB_FILE_TYPES, CompleteUploadRequest, CreateUploadRequest, PresignPartsRequest
from .kb_upload_store import (
    complete_payload,
    list_uploaded_parts,
    load_upload_session,
    persist_upload_parts,
    serialize_upload_session,
    update_upload_status,
)


router = APIRouter()


@router.post("/api/v1/kb/uploads")
def create_upload(payload: CreateUploadRequest, request: Request, user: CurrentUser) -> dict[str, object]:
    require_kb_permission(request, user, KB_WRITE_PERMISSION, action="kb.upload.create", resource_type="upload_session")
    state = begin_idempotency(
        request,
        user,
        request_scope="kb.upload.create",
        payload={
            "base_id": payload.base_id,
            "file_name": payload.file_name,
            "file_type": payload.file_type,
            "size_bytes": payload.size_bytes,
            "category": payload.category,
        },
    )
    if state.replay_payload is not None:
        return state.replay_payload
    try:
        file_type = payload.file_type.lower().lstrip(".")
        if file_type not in ALLOWED_KB_FILE_TYPES:
            raise_api_error(400, "unsupported_file_type", f"unsupported kb file type: {file_type}")
        ensure_base_exists(payload.base_id, user=user, request=request, action="kb.upload.create")
        upload_id = str(uuid4())
        storage_key = storage.build_storage_key(service="kb", document_id=upload_id, file_name=payload.file_name)
        s3_upload_id = storage.create_multipart_upload(
            storage_key,
            metadata={"upload_id": upload_id, "base_id": payload.base_id, "created_by": user.user_id},
        )
        with db.connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO kb_upload_sessions (
                        id, base_id, file_name, file_type, size_bytes, category,
                        storage_key, s3_upload_id, status, created_by, expires_at
                    )
                    VALUES (
                        %s, %s, %s, %s, %s, %s,
                        %s, %s, 'pending_upload', %s, NOW() + INTERVAL '1 hour'
                    )
                    """,
                    (
                        upload_id,
                        payload.base_id,
                        payload.file_name,
                        file_type,
                        payload.size_bytes,
                        payload.category.strip(),
                        storage_key,
                        s3_upload_id,
                        user.user_id,
                    ),
                )
            conn.commit()
        audit_event(
            action="kb.upload.create",
            outcome="success",
            request=request,
            user=user,
            resource_type="upload_session",
            resource_id=upload_id,
            scope="owner",
            details={"base_id": payload.base_id, "file_name": payload.file_name},
        )
        result = serialize_upload_session(load_upload_session(upload_id, user=user, request=request, action="kb.upload.get"))
    except Exception as exc:
        fail_idempotency(state, user, exc)
        KB_UPLOAD_REQUESTS_TOTAL.labels("create_error").inc()
        raise
    complete_idempotency(state, user, response_payload=result, resource_id=upload_id)
    KB_UPLOAD_REQUESTS_TOTAL.labels("create_success").inc()
    return result


@router.get("/api/v1/kb/uploads/{upload_id}")
def get_upload(upload_id: str, request: Request, user: CurrentUser) -> dict[str, object]:
    require_kb_permission(request, user, KB_READ_PERMISSION, action="kb.upload.get", resource_type="upload_session", resource_id=upload_id)
    session = load_upload_session(upload_id, user=user, request=request, action="kb.upload.get")
    return serialize_upload_session(session)


@router.post("/api/v1/kb/uploads/{upload_id}/parts/presign")
def presign_upload_parts(upload_id: str, payload: PresignPartsRequest, request: Request, user: CurrentUser) -> dict[str, object]:
    require_kb_permission(request, user, KB_WRITE_PERMISSION, action="kb.upload.presign", resource_type="upload_session", resource_id=upload_id)
    session = load_upload_session(upload_id, user=user, request=request, action="kb.upload.presign")
    uploaded_parts = list_uploaded_parts(session)
    uploaded_numbers = {item["part_number"] for item in uploaded_parts}
    urls = []
    for part_number in payload.part_numbers:
        if part_number in uploaded_numbers:
            continue
        urls.append(
            {
                "part_number": int(part_number),
                "url": storage.presign_upload_part(
                    str(session["storage_key"]),
                    str(session["s3_upload_id"]),
                    int(part_number),
                    expires_in=UPLOAD_PART_EXPIRES_SECONDS,
                ),
            }
        )
    update_upload_status(upload_id, "uploading")
    return {"upload_id": upload_id, "uploaded_parts": uploaded_parts, "presigned_parts": urls, "chunk_size_bytes": 5 * 1024 * 1024}


@router.post("/api/v1/kb/uploads/{upload_id}/complete")
def complete_upload(upload_id: str, payload: CompleteUploadRequest, request: Request, user: CurrentUser) -> dict[str, object]:
    require_kb_permission(request, user, KB_WRITE_PERMISSION, action="kb.upload.complete", resource_type="upload_session", resource_id=upload_id)
    state = begin_idempotency(
        request,
        user,
        request_scope="kb.upload.complete",
        payload={
            "upload_id": upload_id,
            "parts": [{"part_number": int(item.part_number), "etag": item.etag, "size_bytes": int(item.size_bytes)} for item in payload.parts],
            "content_hash": payload.content_hash.strip(),
        },
    )
    if state.replay_payload is not None:
        return state.replay_payload
    try:
        session = load_upload_session(upload_id, user=user, request=request, action="kb.upload.complete")
        if session.get("document_id"):
            result = complete_payload(document_id=str(session["document_id"]), upload_id=upload_id)
            complete_idempotency(state, user, response_payload=result, resource_id=upload_id)
            KB_UPLOAD_REQUESTS_TOTAL.labels("complete_replay").inc()
            return result
        parts = [{"PartNumber": int(item.part_number), "ETag": item.etag, "size_bytes": int(item.size_bytes)} for item in payload.parts] or list_uploaded_parts(session, internal_shape=True)
        if not parts:
            raise_api_error(400, "missing_upload_parts", "no uploaded parts found")
        storage.complete_multipart_upload(
            str(session["storage_key"]),
            str(session["s3_upload_id"]),
            [{"PartNumber": item["PartNumber"], "ETag": item["ETag"]} for item in sorted(parts, key=lambda row: row["PartNumber"])],
        )
        persist_upload_parts(upload_id, parts)
        object_meta = storage.stat_object(str(session["storage_key"]))
        document_id = str(uuid4())
        job_id = str(uuid4())
        with db.connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO kb_documents (
                        id, base_id, file_name, file_type, content_hash, storage_path,
                        storage_key, size_bytes, status, query_ready, enhancement_status,
                        created_by, stats_json, upload_session_id
                    )
                    VALUES (
                        %s, %s, %s, %s, %s, %s,
                        %s, %s, 'uploaded', FALSE, '', %s, %s::jsonb, %s
                    )
                    """,
                    (
                        document_id,
                        session["base_id"],
                        session["file_name"],
                        session["file_type"],
                        payload.content_hash.strip(),
                        "",
                        session["storage_key"],
                        int(object_meta.get("ContentLength") or session["size_bytes"]),
                        user.user_id,
                        to_json({"category": session.get("category", "")}),
                        upload_id,
                    ),
                )
                cur.execute(
                    """
                    INSERT INTO kb_ingest_jobs (
                        id, document_id, status, phase, query_ready, enhancement_status, checkpoint_json, max_attempts, next_retry_at
                    )
                    VALUES (%s, %s, 'queued', 'uploaded', FALSE, '', '{}'::jsonb, %s, NOW())
                    """,
                    (job_id, document_id, DEFAULT_INGEST_MAX_ATTEMPTS),
                )
                cur.execute(
                    """
                    UPDATE kb_upload_sessions
                    SET status = 'completed',
                        content_hash = %s,
                        document_id = %s,
                        completed_at = NOW(),
                        updated_at = NOW()
                    WHERE id = %s
                    """,
                    (payload.content_hash.strip(), document_id, upload_id),
                )
                cur.execute(
                    """
                    INSERT INTO kb_document_events (document_id, stage, message, details_json)
                    VALUES (%s, 'uploaded', 'multipart upload completed', %s::jsonb)
                    """,
                    (document_id, to_json({"job_id": job_id, "size_bytes": int(object_meta.get("ContentLength") or 0)})),
                )
            conn.commit()
        audit_event(
            action="kb.upload.complete",
            outcome="success",
            request=request,
            user=user,
            resource_type="upload_session",
            resource_id=upload_id,
            scope="owner",
            details={"document_id": document_id, "base_id": str(session.get("base_id") or "")},
        )
        result = complete_payload(document_id=document_id, upload_id=upload_id)
    except Exception as exc:
        fail_idempotency(state, user, exc)
        KB_UPLOAD_REQUESTS_TOTAL.labels("complete_error").inc()
        raise
    complete_idempotency(state, user, response_payload=result, resource_id=upload_id)
    KB_UPLOAD_REQUESTS_TOTAL.labels("complete_success").inc()
    return result
