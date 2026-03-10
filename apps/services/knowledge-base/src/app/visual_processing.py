from __future__ import annotations

import hashlib
import io
import zipfile
from dataclasses import dataclass
from pathlib import Path

from pypdf import PdfReader


IMAGE_FILE_TYPES = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg"}
DOCX_MEDIA_PREFIX = "word/media/"


@dataclass(frozen=True)
class ExtractedVisualAsset:
    asset_index: int
    file_name: str
    mime_type: str
    image_bytes: bytes
    page_number: int | None = None
    source_kind: str = "embedded"
    width: int = 0
    height: int = 0

    @property
    def content_hash(self) -> str:
        return hashlib.sha256(self.image_bytes).hexdigest()

    @property
    def size_bytes(self) -> int:
        return len(self.image_bytes)


def extract_visual_assets(path: Path, file_type: str) -> list[ExtractedVisualAsset]:
    normalized = file_type.lower().lstrip(".")
    if normalized in IMAGE_FILE_TYPES:
        mime_type = IMAGE_FILE_TYPES[normalized]
        raw_bytes = path.read_bytes()
        width, height = _measure_image(raw_bytes)
        return [
            ExtractedVisualAsset(
                asset_index=1,
                file_name=path.name,
                mime_type=mime_type,
                image_bytes=raw_bytes,
                page_number=1,
                source_kind="standalone",
                width=width,
                height=height,
            )
        ]
    if normalized == "pdf":
        return _extract_pdf_images(path)
    if normalized == "docx":
        return _extract_docx_images(path)
    return []


def build_thumbnail_bytes(image_bytes: bytes, *, max_side: int) -> bytes:
    image = _load_pillow_image(image_bytes)
    image.thumbnail((max_side, max_side))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def _extract_pdf_images(path: Path) -> list[ExtractedVisualAsset]:
    reader = PdfReader(str(path))
    assets: list[ExtractedVisualAsset] = []
    asset_index = 1
    for page_number, page in enumerate(reader.pages, start=1):
        try:
            images = list(page.images)
        except Exception:
            images = []
        for image in images:
            raw_bytes = bytes(image.data)
            width, height = _measure_image(raw_bytes)
            file_name = str(getattr(image, "name", "") or f"page-{page_number}-image-{asset_index}.bin")
            mime_type = _mime_from_name(file_name)
            assets.append(
                ExtractedVisualAsset(
                    asset_index=asset_index,
                    file_name=file_name,
                    mime_type=mime_type,
                    image_bytes=raw_bytes,
                    page_number=page_number,
                    source_kind="embedded",
                    width=width,
                    height=height,
                )
            )
            asset_index += 1
    return assets


def _extract_docx_images(path: Path) -> list[ExtractedVisualAsset]:
    assets: list[ExtractedVisualAsset] = []
    asset_index = 1
    with zipfile.ZipFile(path) as archive:
        for name in sorted(archive.namelist()):
            if not name.startswith(DOCX_MEDIA_PREFIX):
                continue
            raw_bytes = archive.read(name)
            width, height = _measure_image(raw_bytes)
            file_name = name.split("/")[-1]
            assets.append(
                ExtractedVisualAsset(
                    asset_index=asset_index,
                    file_name=file_name,
                    mime_type=_mime_from_name(file_name),
                    image_bytes=raw_bytes,
                    page_number=None,
                    source_kind="embedded",
                    width=width,
                    height=height,
                )
            )
            asset_index += 1
    return assets


def _measure_image(image_bytes: bytes) -> tuple[int, int]:
    image = _load_pillow_image(image_bytes)
    return int(image.width or 0), int(image.height or 0)


def _load_pillow_image(image_bytes: bytes):
    from PIL import Image

    image = Image.open(io.BytesIO(image_bytes))
    image.load()
    return image


def _mime_from_name(file_name: str) -> str:
    suffix = Path(file_name).suffix.lower().lstrip(".")
    return IMAGE_FILE_TYPES.get(suffix, "image/png")
