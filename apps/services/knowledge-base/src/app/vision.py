from __future__ import annotations

import base64
import hashlib
import io
import json
import os
import subprocess
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx
from PIL import Image, ImageOps, UnidentifiedImageError
from pypdf import PdfReader


IMAGE_FILE_TYPES = {"png", "jpg", "jpeg"}


def _read_env(*names: str, default: str = "") -> str:
    for name in names:
        raw = os.getenv(name)
        if raw is None:
            continue
        candidate = raw.strip()
        if candidate:
            return candidate
    return default


def _read_int(*names: str, default: int) -> int:
    raw = _read_env(*names, default="")
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _read_float(*names: str, default: float) -> float:
    raw = _read_env(*names, default="")
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


@dataclass(frozen=True)
class VisionSettings:
    provider: str
    fallback_provider: str
    tesseract_cmd: str
    tesseract_lang: str
    api_base_url: str
    api_key: str
    model: str
    timeout_seconds: float
    min_edge_px: int
    min_text_chars: int
    max_assets_per_document: int
    thumbnail_max_edge_px: int

    @property
    def provider_chain(self) -> list[str]:
        ordered = [self.provider, self.fallback_provider]
        chain: list[str] = []
        for item in ordered:
            normalized = item.strip().lower()
            if not normalized or normalized in chain:
                continue
            chain.append(normalized)
        return chain

    @property
    def thumbnail_max_side(self) -> int:
        return self.thumbnail_max_edge_px


@dataclass(frozen=True)
class ExtractedVisualAsset:
    id: str
    asset_index: int
    source_kind: str
    page_number: int | None
    file_name: str
    mime_type: str
    data: bytes
    width: int
    height: int
    content_hash: str

    @property
    def image_bytes(self) -> bytes:
        return self.data

    @property
    def width_px(self) -> int:
        return self.width

    @property
    def height_px(self) -> int:
        return self.height


@dataclass(frozen=True)
class VisualOcrResult:
    status: str
    provider: str
    text: str
    summary: str
    confidence: float | None = None
    error_message: str = ""

    @property
    def ocr_text(self) -> str:
        return self.text


class VisionProviderError(RuntimeError):
    pass


def load_vision_settings() -> VisionSettings:
    return VisionSettings(
        provider=_read_env("VISION_PROVIDER", default="local"),
        fallback_provider=_read_env("VISION_FALLBACK_PROVIDER", default="external"),
        tesseract_cmd=_read_env("VISION_TESSERACT_CMD", default="tesseract"),
        tesseract_lang=_read_env("VISION_TESSERACT_LANG", default="eng+chi_sim"),
        api_base_url=_read_env("VISION_API_BASE_URL", "LLM_BASE_URL", default="").rstrip("/"),
        api_key=_read_env("VISION_API_KEY", "LLM_API_KEY", default=""),
        model=_read_env("VISION_MODEL", default=""),
        timeout_seconds=max(_read_float("VISION_TIMEOUT_SECONDS", default=60.0), 5.0),
        min_edge_px=max(_read_int("VISION_MIN_EDGE_PX", default=120), 1),
        min_text_chars=max(_read_int("VISION_MIN_TEXT_CHARS", default=6), 0),
        max_assets_per_document=max(_read_int("VISION_MAX_ASSETS_PER_DOCUMENT", default=48), 1),
        thumbnail_max_edge_px=max(_read_int("VISION_THUMBNAIL_MAX_EDGE_PX", default=360), 64),
    )


def supports_visual_assets(file_type: str) -> bool:
    normalized = (file_type or "").strip().lower()
    return normalized in {"pdf", "docx", *IMAGE_FILE_TYPES}


def extract_visual_assets(path: Path, file_type: str, max_assets: int | None = None) -> list[ExtractedVisualAsset]:
    normalized = (file_type or "").strip().lower()
    if normalized in IMAGE_FILE_TYPES:
        asset = _normalize_image_asset(
            asset_index=1,
            source_kind="standalone",
            page_number=1,
            file_name=path.name,
            raw_bytes=path.read_bytes(),
        )
        items = [asset] if asset else []
    elif normalized == "pdf":
        items = _extract_pdf_assets(path)
    elif normalized == "docx":
        items = _extract_docx_assets(path)
    else:
        items = []
    if max_assets is not None and max_assets > 0:
        return items[:max_assets]
    return items


def describe_visual_asset(image_bytes: bytes, mime_type: str, *, settings: VisionSettings | None = None) -> VisualOcrResult:
    config = settings or load_vision_settings()
    last_error = ""
    for provider in config.provider_chain:
        if provider == "disabled":
            continue
        try:
            if provider == "local":
                result = _describe_with_local_ocr(image_bytes, mime_type, config)
            elif provider == "external":
                result = _describe_with_external_ocr(image_bytes, mime_type, config)
            else:
                continue
            if result.status == "ready" and len(result.text) < config.min_text_chars:
                return VisualOcrResult(status="no_text", provider=provider, text="", summary="", confidence=result.confidence)
            return result
        except Exception as exc:
            last_error = str(exc)
    return VisualOcrResult(
        status="failed",
        provider=config.provider_chain[-1] if config.provider_chain else "",
        text="",
        summary="",
        error_message=last_error,
    )


def perform_ocr(image_bytes: bytes, mime_type: str, *, settings: VisionSettings | None = None) -> VisualOcrResult:
    result = describe_visual_asset(image_bytes, mime_type, settings=settings)
    if result.status == "failed":
        raise VisionProviderError(result.error_message or "visual OCR failed")
    return result


def run_ocr(asset: ExtractedVisualAsset, settings: VisionSettings | None = None) -> VisualOcrResult:
    return perform_ocr(asset.data, asset.mime_type, settings=settings)


def build_thumbnail(image_bytes: bytes, *, max_edge_px: int) -> tuple[bytes, str]:
    with Image.open(io.BytesIO(image_bytes)) as image:
        prepared = ImageOps.exif_transpose(image)
        if prepared.mode not in {"RGB", "L"}:
            prepared = prepared.convert("RGB")
        elif prepared.mode == "L":
            prepared = prepared.convert("RGB")
        prepared.thumbnail((max_edge_px, max_edge_px))
        buffer = io.BytesIO()
        prepared.save(buffer, format="JPEG", quality=82, optimize=True)
    return buffer.getvalue(), "image/jpeg"


def _extract_pdf_assets(path: Path) -> list[ExtractedVisualAsset]:
    reader = PdfReader(str(path))
    items: list[ExtractedVisualAsset] = []
    asset_index = 1
    for page_number, page in enumerate(reader.pages, start=1):
        images = list(getattr(page, "images", []) or [])
        for image_index, image_file in enumerate(images, start=1):
            raw_bytes = bytes(getattr(image_file, "data", b"") or b"")
            name = str(getattr(image_file, "name", "") or f"page-{page_number}-image-{image_index}.png")
            asset = _normalize_image_asset(
                asset_index=asset_index,
                source_kind="embedded",
                page_number=page_number,
                file_name=name,
                raw_bytes=raw_bytes,
            )
            if asset is None:
                continue
            items.append(asset)
            asset_index += 1
    return items


def _extract_docx_assets(path: Path) -> list[ExtractedVisualAsset]:
    items: list[ExtractedVisualAsset] = []
    asset_index = 1
    with zipfile.ZipFile(path) as archive:
        media_names = sorted(name for name in archive.namelist() if name.startswith("word/media/"))
        for name in media_names:
            asset = _normalize_image_asset(
                asset_index=asset_index,
                source_kind="embedded",
                page_number=asset_index,
                file_name=Path(name).name,
                raw_bytes=archive.read(name),
            )
            if asset is None:
                continue
            items.append(asset)
            asset_index += 1
    return items


def _normalize_image_asset(
    *,
    asset_index: int,
    source_kind: str,
    page_number: int | None,
    file_name: str,
    raw_bytes: bytes,
) -> ExtractedVisualAsset | None:
    if not raw_bytes:
        return None
    try:
        with Image.open(io.BytesIO(raw_bytes)) as image:
            prepared = ImageOps.exif_transpose(image)
            width_px, height_px = prepared.size
            format_name = (prepared.format or "").upper()
            mime_type = Image.MIME.get(format_name, "image/png")
            if prepared.mode not in {"RGB", "RGBA", "L"}:
                prepared = prepared.convert("RGB")
            buffer = io.BytesIO()
            save_format = "PNG" if format_name == "PNG" else "JPEG"
            if save_format == "JPEG":
                prepared = prepared.convert("RGB")
                prepared.save(buffer, format="JPEG", quality=92)
                mime_type = "image/jpeg"
            else:
                prepared.save(buffer, format="PNG")
                mime_type = "image/png"
    except (UnidentifiedImageError, OSError):
        return None
    data = buffer.getvalue()
    return ExtractedVisualAsset(
        id=str(uuid4()),
        asset_index=asset_index,
        source_kind=source_kind,
        page_number=page_number,
        file_name=file_name,
        mime_type=mime_type,
        data=data,
        width=width_px,
        height=height_px,
        content_hash=hashlib.sha256(data).hexdigest(),
    )


def _describe_with_local_ocr(image_bytes: bytes, mime_type: str, settings: VisionSettings) -> VisualOcrResult:
    cleaned = _clean_ocr_text(_run_local_ocr(image_bytes, mime_type, settings))
    if not cleaned:
        return VisualOcrResult(status="no_text", provider="local", text="", summary="")
    return VisualOcrResult(
        status="ready",
        provider="local",
        text=cleaned,
        summary=_summarize_text(cleaned, 220),
        confidence=None,
    )


def _describe_with_external_ocr(image_bytes: bytes, mime_type: str, settings: VisionSettings) -> VisualOcrResult:
    payload = _run_external_ocr(image_bytes, mime_type, settings)
    cleaned = _clean_ocr_text(str(payload.get("ocr_text") or ""))
    if not cleaned:
        return VisualOcrResult(status="no_text", provider="external", text="", summary="")
    summary = str(payload.get("summary") or "").strip() or _summarize_text(cleaned, 220)
    confidence_raw = payload.get("confidence")
    confidence = float(confidence_raw) if isinstance(confidence_raw, (int, float)) else None
    return VisualOcrResult(
        status="ready",
        provider="external",
        text=cleaned,
        summary=summary,
        confidence=confidence,
    )


def _run_local_ocr(image_bytes: bytes, mime_type: str, settings: VisionSettings) -> str:
    suffix = ".png" if mime_type == "image/png" else ".jpg"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as handle:
        handle.write(image_bytes)
        temp_path = Path(handle.name)
    try:
        result = subprocess.run(
            [settings.tesseract_cmd, str(temp_path), "stdout", "-l", settings.tesseract_lang],
            check=False,
            capture_output=True,
            text=True,
            timeout=settings.timeout_seconds,
        )
    finally:
        try:
            temp_path.unlink(missing_ok=True)
        except OSError:
            pass
    if result.returncode != 0:
        stderr = result.stderr.strip()
        raise RuntimeError(stderr or "local OCR failed")
    return result.stdout


def _run_external_ocr(image_bytes: bytes, mime_type: str, settings: VisionSettings) -> dict[str, Any]:
    if not settings.api_base_url or not settings.api_key or not settings.model:
        raise RuntimeError("external vision provider is not configured")
    data_url = f"data:{mime_type};base64,{base64.b64encode(image_bytes).decode('ascii')}"
    request_body = {
        "model": settings.model,
        "temperature": 0.1,
        "max_tokens": 900,
        "messages": [
            {
                "role": "system",
                "content": "You extract readable text from enterprise document screenshots. Respond with strict JSON: {\"ocr_text\":\"...\",\"summary\":\"...\",\"confidence\":0.0}.",
            },
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": "Extract the screenshot text faithfully. Keep important table rows and labels. Return JSON only.",
                    },
                    {
                        "type": "image_url",
                        "image_url": {"url": data_url},
                    },
                ],
            },
        ],
        "response_format": {"type": "json_object"},
    }
    headers = {
        "Authorization": f"Bearer {settings.api_key}",
        "Content-Type": "application/json",
    }
    timeout = httpx.Timeout(settings.timeout_seconds)
    with httpx.Client(timeout=timeout) as client:
        response = client.post(f"{settings.api_base_url}/chat/completions", headers=headers, json=request_body)
    if response.status_code >= 400:
        raise RuntimeError(f"external vision provider returned {response.status_code}")
    payload = response.json()
    choices = payload.get("choices") if isinstance(payload, dict) else None
    if not isinstance(choices, list) or not choices:
        raise RuntimeError("external vision provider returned no choices")
    choice = choices[0] if isinstance(choices[0], dict) else {}
    message = choice.get("message") if isinstance(choice, dict) else {}
    content = _extract_text_content(message.get("content") if isinstance(message, dict) else "")
    if not content:
        raise RuntimeError("external vision provider returned empty content")
    return _parse_json_object(content)


def _extract_text_content(content: Any) -> str:
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                cleaned = item.strip()
                if cleaned:
                    parts.append(cleaned)
                continue
            if not isinstance(item, dict):
                continue
            text_value = item.get("text")
            if isinstance(text_value, str) and text_value.strip():
                parts.append(text_value.strip())
        return "\n".join(parts).strip()
    return ""


def _parse_json_object(raw: str) -> dict[str, Any]:
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        if cleaned.lower().startswith("json"):
            cleaned = cleaned[4:].strip()
    try:
        payload = json.loads(cleaned)
    except json.JSONDecodeError:
        return {"ocr_text": cleaned, "summary": _summarize_text(cleaned, 220)}
    return payload if isinstance(payload, dict) else {"ocr_text": cleaned, "summary": _summarize_text(cleaned, 220)}


def _clean_ocr_text(text: str) -> str:
    return "\n".join(line.rstrip() for line in text.splitlines() if line.strip()).strip()


def _summarize_text(text: str, limit: int) -> str:
    compact = " ".join(part.strip() for part in text.splitlines() if part.strip())
    return compact[:limit].strip()
