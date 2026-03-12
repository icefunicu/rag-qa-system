from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, field_validator


ALLOWED_EXECUTION_MODES = {"grounded", "agent"}
ALLOWED_AGENT_TOOLS = {"search_scope", "list_scope_documents", "search_corpus", "calculator"}


class LoginRequest(BaseModel):
    email: str
    password: str


class ChatScopePayload(BaseModel):
    mode: str = Field(default="all", max_length=16)
    corpus_ids: list[str] = Field(default_factory=list)
    document_ids: list[str] = Field(default_factory=list)
    allow_common_knowledge: bool = False
    agent_profile_id: str = Field(default="", max_length=64)
    prompt_template_id: str = Field(default="", max_length=64)


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


class CreateThreadRequest(CreateSessionRequest):
    pass


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


class CreateRunRequest(SendMessageRequest):
    pass


class RetryWorkflowRunRequest(BaseModel):
    reuse_scope: bool = True


class SubmitInterruptRequest(BaseModel):
    question: str = Field(default="", max_length=12000)
    allow_common_knowledge: bool | None = None

    @field_validator("question")
    @classmethod
    def normalize_question(cls, value: str) -> str:
        return value.strip()


class MessageFeedbackRequest(BaseModel):
    verdict: str = Field(min_length=1, max_length=16)
    reason_code: str = Field(default="", max_length=64)
    notes: str = Field(default="", max_length=1000)

    @field_validator("verdict")
    @classmethod
    def validate_verdict(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in {"up", "down", "flag"}:
            raise ValueError(f"unsupported feedback verdict: {normalized}")
        return normalized

    @field_validator("reason_code")
    @classmethod
    def normalize_reason_code(cls, value: str) -> str:
        return value.strip().lower().replace(" ", "_")

    @field_validator("notes")
    @classmethod
    def normalize_notes(cls, value: str) -> str:
        return value.strip()


class PromptTemplateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    content: str = Field(min_length=1, max_length=4000)
    visibility: str = Field(default="personal", max_length=16)
    tags: list[str] = Field(default_factory=list, max_length=16)
    favorite: bool = False

    @field_validator("name", "content")
    @classmethod
    def normalize_required_text(cls, value: str) -> str:
        return value.strip()

    @field_validator("visibility")
    @classmethod
    def validate_visibility(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in {"personal", "public"}:
            raise ValueError(f"unsupported visibility: {normalized}")
        return normalized

    @field_validator("tags")
    @classmethod
    def normalize_tags(cls, value: list[str]) -> list[str]:
        normalized = [str(item).strip().lower().replace(" ", "_") for item in value if str(item).strip()]
        return list(dict.fromkeys(normalized))[:16]


class UpdatePromptTemplateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    content: str | None = Field(default=None, min_length=1, max_length=4000)
    visibility: str | None = Field(default=None, max_length=16)
    tags: list[str] | None = None
    favorite: bool | None = None

    @field_validator("name", "content")
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        return value.strip() if value is not None else None

    @field_validator("visibility")
    @classmethod
    def validate_optional_visibility(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip().lower()
        if normalized not in {"personal", "public"}:
            raise ValueError(f"unsupported visibility: {normalized}")
        return normalized

    @field_validator("tags")
    @classmethod
    def normalize_optional_tags(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        normalized = [str(item).strip().lower().replace(" ", "_") for item in value if str(item).strip()]
        return list(dict.fromkeys(normalized))[:16]


class AgentProfileRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=500)
    persona_prompt: str = Field(default="", max_length=4000)
    enabled_tools: list[str] = Field(default_factory=list, max_length=16)
    default_corpus_ids: list[str] = Field(default_factory=list, max_length=32)
    prompt_template_id: str = Field(default="", max_length=64)

    @field_validator("name", "description", "persona_prompt", "prompt_template_id")
    @classmethod
    def normalize_profile_text(cls, value: str) -> str:
        return value.strip()

    @field_validator("enabled_tools")
    @classmethod
    def validate_enabled_tools(cls, value: list[str]) -> list[str]:
        normalized = [str(item).strip().lower() for item in value if str(item).strip()]
        invalid = [item for item in normalized if item not in ALLOWED_AGENT_TOOLS]
        if invalid:
            raise ValueError(f"unsupported agent tools: {', '.join(invalid)}")
        return list(dict.fromkeys(normalized))

    @field_validator("default_corpus_ids")
    @classmethod
    def normalize_corpus_ids(cls, value: list[str]) -> list[str]:
        return list(dict.fromkeys(str(item).strip() for item in value if str(item).strip()))


class UpdateAgentProfileRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=500)
    persona_prompt: str | None = Field(default=None, max_length=4000)
    enabled_tools: list[str] | None = None
    default_corpus_ids: list[str] | None = None
    prompt_template_id: str | None = Field(default=None, max_length=64)

    @field_validator("name", "description", "persona_prompt", "prompt_template_id")
    @classmethod
    def normalize_optional_profile_text(cls, value: str | None) -> str | None:
        return value.strip() if value is not None else None

    @field_validator("enabled_tools")
    @classmethod
    def validate_optional_tools(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        normalized = [str(item).strip().lower() for item in value if str(item).strip()]
        invalid = [item for item in normalized if item not in ALLOWED_AGENT_TOOLS]
        if invalid:
            raise ValueError(f"unsupported agent tools: {', '.join(invalid)}")
        return list(dict.fromkeys(normalized))

    @field_validator("default_corpus_ids")
    @classmethod
    def normalize_optional_corpus_ids(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        return list(dict.fromkeys(str(item).strip() for item in value if str(item).strip()))


class AnalyticsDashboardResponse(BaseModel):
    view: str = Field(description="Analytics scope. personal only includes the caller's activity; admin includes all visible activity.")
    days: int = Field(description="Rolling window in days for funnel, QA, and trend metrics.", ge=1, le=90)
    hot_terms: list[dict[str, Any]] = Field(description="Recent high-frequency user question tokens from the chat flow.")
    zero_hit: dict[str, Any] = Field(description="Existing zero-hit trend and top-query aggregates based on missing citations or zero selected candidates.")
    satisfaction: dict[str, Any] = Field(description="User feedback trend for up, down, and flag verdicts.")
    usage: dict[str, Any] = Field(description="Assistant token and estimated cost usage summary with day-level trend.")
    funnel: dict[str, Any] = Field(description="Core funnel metrics spanning KB creation, ingest progress, Q&A turns, answer outcomes, and user feedback.")
    ingest_health: dict[str, Any] | None = Field(default=None, description="Knowledge-base ingest health snapshot. Null when KB analytics data is temporarily unavailable.")
    qa_quality: dict[str, Any] = Field(description="Answer-mode, evidence-status, zero-hit, and low-quality aggregates for front-end quality dashboards.")
    data_quality: dict[str, Any] = Field(description="Unsupported fields or degraded sections. Frontend should inspect this section to handle null analytics values.")
