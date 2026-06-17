from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator


MEMORY_TYPES = frozenset(
    {
        "preference",
        "feedback",
        "reading_state",
        "correction",
        "forget",
    }
)
MEMORY_SUBJECTS = frozenset(
    {
        "user",
        "book",
        "author",
        "tag",
        "theme",
        "style",
        "genre",
        "mood",
        "pacing",
        "content",
    }
)
MEMORY_POLARITIES = frozenset(
    {
        "like",
        "dislike",
        "neutral",
        "want",
        "read",
        "avoid",
    }
)
MEMORY_SOURCES = frozenset({"chat_turn", "tool", "manual"})


def normalize_memory_token(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip().lower().replace(" ", "_")


def normalize_memory_value(value: Any) -> str:
    return str(value or "").strip()


def validate_memory_token(field_name: str, value: Any, allowed: frozenset[str]) -> str:
    token = normalize_memory_token(str(value or ""))
    if token not in allowed:
        allowed_values = ", ".join(sorted(allowed))
        raise ValueError(f"{field_name} must be one of: {allowed_values}")
    return token


def validate_optional_memory_token(
    field_name: str,
    value: Any,
    allowed: frozenset[str],
) -> str:
    token = normalize_memory_token(str(value or ""))
    if not token:
        return ""
    if token not in allowed:
        allowed_values = ", ".join(sorted(allowed))
        raise ValueError(f"{field_name} must be empty or one of: {allowed_values}")
    return token


class MemoryEvent(BaseModel):
    """Application-owned memory event contract shared by memory providers."""

    id: UUID | None = None
    type: str = Field(
        description="Memory type: preference, feedback, reading_state, correction, or forget."
    )
    subject: str = Field(
        description=(
            "Memory subject: user, book, author, tag, theme, style, genre, mood, "
            "pacing, or content."
        )
    )
    value: str = Field(description="Concise memory value in natural language.")
    polarity: str = Field(
        default="neutral",
        description="like, dislike, neutral, want, read, or avoid.",
    )
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    user_id: UUID
    thread_id: UUID | None = None
    source: str = Field(default="chat_turn", description="chat_turn, tool, or manual.")
    metadata: dict[str, Any] = Field(default_factory=dict)
    revision_of: UUID | None = None
    superseded_by: UUID | None = None
    forgotten: bool = Field(
        default=False,
        validation_alias=AliasChoices("forgotten", "is_deleted"),
        description="Whether this memory has been forgotten and is no longer active.",
    )
    created_at: datetime | None = None
    updated_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

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

    @field_validator("value", mode="before")
    @classmethod
    def clean_value(cls, value: Any) -> str:
        text = normalize_memory_value(value)
        if not text:
            raise ValueError("value cannot be empty")
        return text


class MemorySearchResult(BaseModel):
    """Aggregated memory search result returned to agents."""

    profile_summary: str = ""
    preferred_tags: list[str] = Field(default_factory=list)
    disliked_tags: list[str] = Field(default_factory=list)
    favorite_authors: list[str] = Field(default_factory=list)
    disliked_authors: list[str] = Field(default_factory=list)
    reading_states: list[dict[str, Any]] = Field(default_factory=list)
    relevant_events: list[MemoryEvent] = Field(default_factory=list)
    provider_sources: list[str] = Field(default_factory=list)


class CurrentMemoryListResult(BaseModel):
    """Current active memories shown in the default user-facing memory view."""

    user_id: UUID
    memories: list[MemoryEvent] = Field(default_factory=list)
    total: int = 0
    limit: int = 50
    offset: int = 0
    provider_sources: list[str] = Field(default_factory=list)


class MemoryEventListResult(BaseModel):
    """Paginated audit event list for advanced memory history."""

    user_id: UUID
    events: list[MemoryEvent] = Field(default_factory=list)
    total: int = 0
    limit: int = 50
    offset: int = 0
    include_forgotten: bool = False
    include_superseded: bool = False
    include_audit: bool = False
    provider_sources: list[str] = Field(default_factory=list)


class MemoryForgetResult(BaseModel):
    """Result for a forget operation."""

    user_id: UUID
    forgotten_count: int
    forgotten_event_ids: list[UUID] = Field(default_factory=list)
    provider_sources: list[str] = Field(default_factory=list)
