from __future__ import annotations

import hashlib
from uuid import uuid4

from fastapi import APIRouter, File, Form, Request, Response, UploadFile

from shared.api_errors import raise_api_error
from shared.auth import CurrentUser

from .db import to_json
from .kb_api_support import audit_event, require_kb_permission
from .kb_resource_store import ensure_base_exists
from .kb_runtime import KB_WRITE_PERMISSION, db, storage
from .kb_schemas import ALLOWED_KB_FILE_TYPES


router = APIRouter()


@router.post("/api/v1/kb/documents/upload")
def upload_documents(
    response: Response,
    request: Request,
    user: CurrentUser,
    base_id: str = Form(...),
    category: str = Form(""),
    files: list[UploadFile] = File(...),
) -> dict[str, object]:
    require_kb_permission(request, user, KB_WRITE_PERMISSION, action="kb.document.legacy_upload", resource_type="knowledge_base", resource_id=base_id)
    response.headers["Deprecation"] = "true"
    response.headers["Link"] = '</api/v1/kb/uploads>; rel="successor-version"'
    ensure_base_exists(base_id, user=user, request=request, action="kb.document.legacy_upload")
    items: list[dict[str, object]] = []
    for upload in files:
        raw = upload.file.read()
        document_id = str(uuid4())
        file_type = (upload.filename or "").split(".")[-1].lower()
        if file_type not in ALLOWED_KB_FILE_TYPES:
            raise_api_error(400, "unsupported_file_type", f"unsupported kb file type: {file_type}")
        storage_key = storage.build_storage_key(service="kb-legacy", document_id=document_id, file_name=upload.filename or "source.bin")
        content_hash = hashlib.sha256(raw).hexdigest()
        storage.put_bytes(storage_key, raw, metadata={"document_id": document_id, "legacy": "true"})
        with db.connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO kb_documents (
                        id, base_id, file_name, file_type, content_hash, storage_path,
                        storage_key, size_bytes, status, query_ready, enhancement_status,
                        created_by, stats_json
                    )
                    VALUES (
                        %s, %s, %s, %s, %s, '', %s, %s,
                        'uploaded', FALSE, '', %s, %s::jsonb
                    )
                    """,
                    (
                        document_id,
                        base_id,
                        upload.filename or "source.bin",
                        file_type,
                        content_hash,
                        storage_key,
                        len(raw),
                        user.user_id,
                        to_json({"category": category.strip(), "legacy_upload": True}),
                    ),
                )
                job_id = str(uuid4())
                cur.execute(
                    """
                    INSERT INTO kb_ingest_jobs (id, document_id, status, phase, checkpoint_json)
                    VALUES (%s, %s, 'queued', 'uploaded', '{}'::jsonb)
                    """,
                    (job_id, document_id),
                )
                cur.execute(
                    """
                    INSERT INTO kb_document_events (document_id, stage, message, details_json)
                    VALUES (%s, 'uploaded', 'legacy direct upload completed', %s::jsonb)
                    """,
                    (document_id, to_json({"job_id": job_id})),
                )
            conn.commit()
        items.append({"document_id": document_id, "job_id": job_id, "status": "uploaded"})
    audit_event(
        action="kb.document.legacy_upload",
        outcome="success",
        request=request,
        user=user,
        resource_type="knowledge_base",
        resource_id=base_id,
        scope="owner",
        details={"file_count": len(items)},
    )
    return {"items": items, "deprecated": True}
