from __future__ import annotations

from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from app.services.memory.contracts import (
    INFORMATION_SCOPES,
    MEMORY_CANDIDATE_SOURCE_KINDS,
    MEMORY_CONFLICT_DECISIONS,
    MEMORY_CONFLICT_SEVERITIES,
    MEMORY_CONFLICT_TYPES,
    MEMORY_POLARITIES,
    MEMORY_SOURCES,
    MEMORY_SUBJECTS,
    MEMORY_TYPES,
    normalize_memory_value,
    validate_memory_token,
    validate_optional_memory_token,
)


class MemoryContractResponse(BaseModel):
    memory_types: list[str]
    subjects: list[str]
    polarities: list[str]
    sources: list[str]
    information_scopes: list[str]
    candidate_source_kinds: list[str]
    admission_decisions: list[str]
    conflict_types: list[str]
    conflict_severities: list[str]
    conflict_decisions: list[str]


class MemoryRememberRequest(BaseModel):
    user_id: UUID
    type: str = Field(description="preference, feedback, reading_state, or correction.")
    subject: str = Field(description="user, book, author, tag, theme, style, or genre.")
    value: str = Field(description="Concise memory value.")
    polarity: str = Field(default="neutral")
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    thread_id: UUID | None = None
    source: str = Field(default="manual")
    scope: str = Field(default="long_term_memory")
    source_kind: str = Field(default="manual")
    source_text: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("type", mode="before")
    @classmethod
    def validate_type(cls, value: Any) -> str:
        return validate_memory_token("type", value, MEMORY_TYPES)

    @field_validator("subject", mode="before")
    @classmethod
    def validate_subject(cls, value: Any) -> str:
        return validate_memory_token("subject", value, MEMORY_SUBJECTS)

    @field_validator("polarity", mode="before")
    @classmethod
    def validate_polarity(cls, value: Any) -> str:
        return validate_memory_token("polarity", value, MEMORY_POLARITIES)

    @field_validator("source", mode="before")
    @classmethod
    def validate_source(cls, value: Any) -> str:
        return validate_memory_token("source", value, MEMORY_SOURCES)

    @field_validator("scope", mode="before")
    @classmethod
    def validate_scope(cls, value: Any) -> str:
        return validate_memory_token("scope", value, INFORMATION_SCOPES)

    @field_validator("source_kind", mode="before")
    @classmethod
    def validate_source_kind(cls, value: Any) -> str:
        return validate_memory_token(
            "source_kind",
            value,
            MEMORY_CANDIDATE_SOURCE_KINDS,
        )

    @field_validator("source_text", mode="before")
    @classmethod
    def clean_source_text(cls, value: Any) -> str:
        return normalize_memory_value(value)

    @field_validator("value", mode="before")
    @classmethod
    def validate_value(cls, value: Any) -> str:
        text = normalize_memory_value(value)
        if not text:
            raise ValueError("value cannot be empty")
        return text


class MemoryReviseRequest(BaseModel):
    user_id: UUID
    memory_id: UUID | None = None
    old_value: str = ""
    old_subject: str = ""
    old_type: str = ""
    new_type: str = "correction"
    new_subject: str
    new_value: str
    new_polarity: str = "neutral"
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    thread_id: UUID | None = None
    source: str = Field(default="manual")
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("old_subject", mode="before")
    @classmethod
    def validate_old_subject(cls, value: Any) -> str:
        return validate_optional_memory_token("old_subject", value, MEMORY_SUBJECTS)

    @field_validator("old_type", mode="before")
    @classmethod
    def validate_old_type(cls, value: Any) -> str:
        return validate_optional_memory_token("old_type", value, MEMORY_TYPES)

    @field_validator("new_type", mode="before")
    @classmethod
    def validate_new_type(cls, value: Any) -> str:
        return validate_memory_token("new_type", value, MEMORY_TYPES)

    @field_validator("new_subject", mode="before")
    @classmethod
    def validate_new_subject(cls, value: Any) -> str:
        return validate_memory_token("new_subject", value, MEMORY_SUBJECTS)

    @field_validator("new_polarity", mode="before")
    @classmethod
    def validate_new_polarity(cls, value: Any) -> str:
        return validate_memory_token("new_polarity", value, MEMORY_POLARITIES)

    @field_validator("source", mode="before")
    @classmethod
    def validate_source(cls, value: Any) -> str:
        return validate_memory_token("source", value, MEMORY_SOURCES)

    @field_validator("new_value", mode="before")
    @classmethod
    def validate_new_value(cls, value: Any) -> str:
        text = normalize_memory_value(value)
        if not text:
            raise ValueError("new_value cannot be empty")
        return text


class MemoryForgetRequest(BaseModel):
    user_id: UUID
    memory_id: UUID | None = None
    subject: str = ""
    value: str = ""
    memory_type: str = ""
    thread_id: UUID | None = None
    reason: str = ""

    @field_validator("subject", mode="before")
    @classmethod
    def validate_subject(cls, value: Any) -> str:
        return validate_optional_memory_token("subject", value, MEMORY_SUBJECTS)

    @field_validator("memory_type", mode="before")
    @classmethod
    def validate_memory_type(cls, value: Any) -> str:
        return validate_optional_memory_token("memory_type", value, MEMORY_TYPES)
