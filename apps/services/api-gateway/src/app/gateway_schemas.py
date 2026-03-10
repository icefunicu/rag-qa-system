from __future__ import annotations

from pydantic import BaseModel, Field, field_validator


ALLOWED_EXECUTION_MODES = {"grounded", "agent"}


class LoginRequest(BaseModel):
    email: str
    password: str


class ChatScopePayload(BaseModel):
    mode: str = Field(default="all", max_length=16)
    corpus_ids: list[str] = Field(default_factory=list)
    document_ids: list[str] = Field(default_factory=list)
    allow_common_knowledge: bool = False


class CreateSessionRequest(BaseModel):
    title: str = Field(default="", max_length=120)
    scope: ChatScopePayload | None = None
    execution_mode: str = Field(default="grounded", max_length=32)

    @field_validator("execution_mode")
    @classmethod
    def validate_execution_mode(cls, value: str) -> str:
        normalized = value.strip().lower() or "grounded"
        if normalized not in ALLOWED_EXECUTION_MODES:
            raise ValueError(f"unsupported execution mode: {normalized}")
        return normalized


class UpdateSessionRequest(BaseModel):
    title: str | None = Field(default=None, max_length=120)
    scope: ChatScopePayload | None = None
    execution_mode: str | None = Field(default=None, max_length=32)

    @field_validator("execution_mode")
    @classmethod
    def validate_optional_execution_mode(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip().lower()
        if normalized not in ALLOWED_EXECUTION_MODES:
            raise ValueError(f"unsupported execution mode: {normalized}")
        return normalized


class SendMessageRequest(BaseModel):
    question: str = Field(min_length=1, max_length=12000)
    scope: ChatScopePayload | None = None
    execution_mode: str | None = Field(default=None, max_length=32)

    @field_validator("execution_mode")
    @classmethod
    def validate_message_execution_mode(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip().lower()
        if normalized not in ALLOWED_EXECUTION_MODES:
            raise ValueError(f"unsupported execution mode: {normalized}")
        return normalized
