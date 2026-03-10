from __future__ import annotations

from pydantic import BaseModel, Field, field_validator


ALLOWED_KB_FILE_TYPES = {"txt", "pdf", "docx", "png", "jpg", "jpeg"}


class CreateBaseRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=2000)
    category: str = Field(default="", max_length=120)


class UpdateBaseRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=2000)
    category: str | None = Field(default=None, max_length=120)


class CreateUploadRequest(BaseModel):
    base_id: str
    file_name: str = Field(min_length=1, max_length=255)
    file_type: str = Field(min_length=1, max_length=16)
    size_bytes: int = Field(gt=0)
    category: str = Field(default="", max_length=120)

    @field_validator("file_type")
    @classmethod
    def validate_file_type(cls, value: str) -> str:
        normalized = value.lower().lstrip(".").strip()
        if normalized not in ALLOWED_KB_FILE_TYPES:
            raise ValueError(f"unsupported kb file type: {normalized}")
        return normalized


class PresignPartsRequest(BaseModel):
    part_numbers: list[int] = Field(min_length=1, max_length=1000)


class UploadPartItem(BaseModel):
    part_number: int = Field(ge=1)
    etag: str = Field(min_length=1, max_length=256)
    size_bytes: int = Field(default=0, ge=0)


class CompleteUploadRequest(BaseModel):
    parts: list[UploadPartItem] = Field(default_factory=list)
    content_hash: str = Field(default="", max_length=128)


class RetrieveRequest(BaseModel):
    base_id: str
    question: str = Field(min_length=1, max_length=12000)
    document_ids: list[str] = Field(default_factory=list)
    limit: int = Field(default=8, ge=1, le=20)


class KBQueryRequest(BaseModel):
    base_id: str
    question: str = Field(min_length=1, max_length=12000)
    document_ids: list[str] = Field(default_factory=list)
    debug: bool = False


class UpdateDocumentRequest(BaseModel):
    file_name: str | None = Field(default=None, min_length=1, max_length=255)
    category: str | None = Field(default=None, max_length=120)
