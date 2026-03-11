from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator


ALLOWED_KB_FILE_TYPES = {"txt", "pdf", "docx", "png", "jpg", "jpeg"}
ALLOWED_CONNECTOR_TYPES = {
    "local_directory",
    "notion",
    "feishu_document",
    "dingtalk_document",
    "web_crawler",
    "sql_query",
}
ALLOWED_DOCUMENT_VERSION_STATUSES = {"active", "draft", "superseded", "archived"}


def _normalize_optional_text(value: str | None, *, field_name: str, allow_blank: bool = False) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    if not normalized and not allow_blank:
        raise ValueError(f"{field_name} must not be blank")
    return normalized


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
    version_family_key: str | None = Field(default=None, max_length=160)
    version_label: str | None = Field(default=None, max_length=64)
    version_number: int | None = Field(default=None, ge=1, le=100000)
    version_status: str | None = Field(default=None, max_length=32)
    is_current_version: bool | None = None
    effective_from: datetime | None = None
    effective_to: datetime | None = None
    supersedes_document_id: str | None = Field(default=None, max_length=64)

    @field_validator("file_type")
    @classmethod
    def validate_file_type(cls, value: str) -> str:
        normalized = value.lower().lstrip(".").strip()
        if normalized not in ALLOWED_KB_FILE_TYPES:
            raise ValueError(f"unsupported kb file type: {normalized}")
        return normalized

    @field_validator("version_family_key")
    @classmethod
    def normalize_version_family_key(cls, value: str | None) -> str | None:
        return _normalize_optional_text(value, field_name="version_family_key")

    @field_validator("version_label")
    @classmethod
    def normalize_version_label(cls, value: str | None) -> str | None:
        return _normalize_optional_text(value, field_name="version_label")

    @field_validator("version_status")
    @classmethod
    def validate_version_status(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = str(_normalize_optional_text(value, field_name="version_status") or "").lower()
        if normalized not in ALLOWED_DOCUMENT_VERSION_STATUSES:
            raise ValueError(f"unsupported version status: {normalized}")
        return normalized

    @field_validator("supersedes_document_id")
    @classmethod
    def normalize_supersedes_document_id(cls, value: str | None) -> str | None:
        return _normalize_optional_text(value, field_name="supersedes_document_id")

    @model_validator(mode="after")
    def validate_version_window(self):
        if self.effective_from and self.effective_to and self.effective_to < self.effective_from:
            raise ValueError("effective_to must be greater than or equal to effective_from")
        if self.is_current_version and self.version_status and self.version_status != "active":
            raise ValueError("current version must use active status")
        return self


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


class RetrievalDebugRequest(RetrieveRequest):
    pass


class KBQueryRequest(BaseModel):
    base_id: str
    question: str = Field(min_length=1, max_length=12000)
    document_ids: list[str] = Field(default_factory=list)
    debug: bool = False


class UpdateDocumentRequest(BaseModel):
    file_name: str | None = Field(default=None, min_length=1, max_length=255)
    category: str | None = Field(default=None, max_length=120)
    version_family_key: str | None = Field(default=None, max_length=160)
    version_label: str | None = Field(default=None, max_length=64)
    version_number: int | None = Field(default=None, ge=1, le=100000)
    version_status: str | None = Field(default=None, max_length=32)
    is_current_version: bool | None = None
    effective_from: datetime | None = None
    effective_to: datetime | None = None
    supersedes_document_id: str | None = Field(default=None, max_length=64)

    @field_validator("version_family_key")
    @classmethod
    def normalize_optional_version_family_key(cls, value: str | None) -> str | None:
        return _normalize_optional_text(value, field_name="version_family_key")

    @field_validator("version_label")
    @classmethod
    def normalize_optional_version_label(cls, value: str | None) -> str | None:
        return _normalize_optional_text(value, field_name="version_label")

    @field_validator("version_status")
    @classmethod
    def validate_optional_version_status(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = str(_normalize_optional_text(value, field_name="version_status") or "").lower()
        if normalized not in ALLOWED_DOCUMENT_VERSION_STATUSES:
            raise ValueError(f"unsupported version status: {normalized}")
        return normalized

    @field_validator("supersedes_document_id")
    @classmethod
    def normalize_optional_supersedes_document_id(cls, value: str | None) -> str | None:
        return _normalize_optional_text(value, field_name="supersedes_document_id")

    @model_validator(mode="after")
    def validate_document_version_window(self):
        if self.effective_from and self.effective_to and self.effective_to < self.effective_from:
            raise ValueError("effective_to must be greater than or equal to effective_from")
        if self.is_current_version and self.version_status and self.version_status != "active":
            raise ValueError("current version must use active status")
        return self


class UpdateChunkRequest(BaseModel):
    text_content: str | None = Field(default=None, min_length=1, max_length=40000)
    disabled: bool | None = None
    disabled_reason: str = Field(default="", max_length=240)
    manual_note: str = Field(default="", max_length=1000)

    @field_validator("text_content")
    @classmethod
    def normalize_text_content(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("text_content must not be blank")
        return normalized

    @field_validator("disabled_reason", "manual_note")
    @classmethod
    def normalize_text_fields(cls, value: str) -> str:
        return value.strip()


class SplitChunkRequest(BaseModel):
    parts: list[str] = Field(min_length=2, max_length=16)

    @field_validator("parts")
    @classmethod
    def validate_parts(cls, value: list[str]) -> list[str]:
        normalized = [str(item).strip() for item in value if str(item).strip()]
        if len(normalized) < 2:
            raise ValueError("parts must contain at least two non-empty text blocks")
        return normalized


class MergeChunksRequest(BaseModel):
    chunk_ids: list[str] = Field(min_length=2, max_length=16)
    separator: str = Field(default="\n\n", max_length=16)

    @field_validator("chunk_ids")
    @classmethod
    def validate_chunk_ids(cls, value: list[str]) -> list[str]:
        normalized = [str(item).strip() for item in value if str(item).strip()]
        if len(normalized) < 2:
            raise ValueError("chunk_ids must contain at least two items")
        return list(dict.fromkeys(normalized))


class LocalDirectorySyncRequest(BaseModel):
    base_id: str
    source_path: str = Field(min_length=1, max_length=1024)
    category: str = Field(default="", max_length=120)
    recursive: bool = True
    delete_missing: bool = True
    dry_run: bool = False
    max_files: int | None = Field(default=None, ge=1, le=5000)


class NotionSyncRequest(BaseModel):
    base_id: str
    page_ids: list[str] = Field(min_length=1, max_length=64)
    category: str = Field(default="", max_length=120)
    delete_missing: bool = True
    dry_run: bool = False
    max_pages: int | None = Field(default=None, ge=1, le=256)

    @field_validator("page_ids")
    @classmethod
    def validate_page_ids(cls, value: list[str]) -> list[str]:
        normalized = [str(item).strip() for item in value if str(item).strip()]
        if not normalized:
            raise ValueError("page_ids must not be empty")
        return normalized


class ConnectorScheduleRequest(BaseModel):
    enabled: bool = False
    interval_minutes: int | None = Field(default=None, ge=15, le=10080)

    @model_validator(mode="after")
    def validate_schedule(self):
        if self.enabled and self.interval_minutes is None:
            raise ValueError("interval_minutes is required when schedule.enabled is true")
        return self


class CreateConnectorRequest(BaseModel):
    base_id: str
    name: str = Field(min_length=1, max_length=120)
    connector_type: str = Field(min_length=1, max_length=64)
    config: dict[str, Any] = Field(default_factory=dict)
    schedule: ConnectorScheduleRequest = Field(default_factory=ConnectorScheduleRequest)

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        return value.strip()

    @field_validator("connector_type")
    @classmethod
    def validate_connector_type(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in ALLOWED_CONNECTOR_TYPES:
            raise ValueError(f"unsupported connector type: {normalized}")
        return normalized


class UpdateConnectorRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    config: dict[str, Any] | None = None
    schedule: ConnectorScheduleRequest | None = None
    status: str | None = Field(default=None, max_length=32)

    @field_validator("name")
    @classmethod
    def normalize_optional_name(cls, value: str | None) -> str | None:
        return value.strip() if value is not None else None

    @field_validator("status")
    @classmethod
    def validate_status(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip().lower()
        if normalized not in {"active", "paused"}:
            raise ValueError(f"unsupported connector status: {normalized}")
        return normalized


class RunConnectorRequest(BaseModel):
    dry_run: bool = False
    limit: int | None = Field(default=None, ge=1, le=64)


class KBAnalyticsDashboardResponse(BaseModel):
    view: str = Field(description="Analytics scope. personal only includes the caller's KB resources; admin includes all visible resources.")
    days: int = Field(description="Rolling window in days for funnel and latency metrics.", ge=1, le=90)
    funnel: dict[str, Any] = Field(description="Core KB funnel metrics for knowledge-base creation, document upload, and document ready transitions.")
    ingest_health: dict[str, Any] = Field(description="Current ingest health snapshot, status distributions, and upload-to-ready latency statistics.")
    data_quality: dict[str, Any] = Field(description="Unsupported or degraded KB analytics fields. Empty arrays mean full support for the current payload.")
