from __future__ import annotations

from fastapi import APIRouter, Request, Response

from shared.auth import CurrentUser

from .kb_api_support import require_kb_permission
from .kb_resource_store import load_visual_asset
from .kb_runtime import KB_READ_PERMISSION, storage


router = APIRouter()


@router.get("/api/v1/kb/visual-assets/{asset_id}/thumbnail")
def get_visual_asset_thumbnail(asset_id: str, request: Request, user: CurrentUser) -> Response:
    require_kb_permission(request, user, KB_READ_PERMISSION, action="kb.visual_asset.thumbnail", resource_type="visual_asset", resource_id=asset_id)
    asset = load_visual_asset(asset_id, user=user, request=request, action="kb.visual_asset.thumbnail")
    thumbnail_key = str(asset.get("thumbnail_key") or asset.get("storage_key") or "")
    body, content_type = storage.get_object_bytes(thumbnail_key)
    return Response(content=body, media_type=content_type)
