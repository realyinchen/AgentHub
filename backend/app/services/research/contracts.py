from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


RESEARCH_RUN_STATUSES = frozenset({"active", "completed", "cancelled", "failed"})
RESEARCH_MODES = frozenset({"deep_search", "deep_research"})
RESEARCH_STEP_TYPES = frozenset(
    {
        "plan",
        "search",
        "visit",
        "add_evidence",
        "update_state",
        "finish",
    }
)
RESEARCH_STEP_STATUSES = frozenset(
    {
        "planned",
        "running",
        "completed",
        "empty_result",
        "timeout",
        "failed",
        "skipped",
    }
)
EVIDENCE_SOURCE_TYPES = frozenset({"web", "book", "paper", "user", "manual", "other"})
EVIDENCE_QUALITIES = frozenset({"high", "medium", "low", "unknown"})


def normalize_research_token(value: Any) -> str:
    return str(value or "").strip().lower().replace(" ", "_")


def normalize_text(value: Any) -> str:
    return str(value or "").strip()


def validate_research_token(
    field_name: str,
    value: Any,
    allowed: frozenset[str],
) -> str:
    token = normalize_research_token(value)
    if token not in allowed:
        allowed_values = ", ".join(sorted(allowed))
        raise ValueError(f"{field_name} must be one of: {allowed_values}")
    return token


def clean_string_list(values: list[Any] | None) -> list[str]:
    seen: set[str] = set()
    cleaned: list[str] = []
    for value in values or []:
        text = normalize_text(value)
        key = text.lower()
        if text and key not in seen:
            seen.add(key)
            cleaned.append(text)
    return cleaned


class ResearchRun(BaseModel):
    """Application-owned contract for one research task."""

    id: UUID | None = None
    user_id: UUID
    thread_id: UUID | None = None
    objective: str
    status: str = "active"
    mode: str = "deep_search"
    budget: dict[str, Any] = Field(default_factory=dict)
    stop_criteria: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    started_at: datetime | None = None
    finished_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)

    @field_validator("objective", mode="before")
    @classmethod
    def clean_objective(cls, value: Any) -> str:
        text = normalize_text(value)
        if not text:
            raise ValueError("objective cannot be empty")
        return text

    @field_validator("status", mode="before")
    @classmethod
    def validate_status(cls, value: Any) -> str:
        return validate_research_token("status", value, RESEARCH_RUN_STATUSES)

    @field_validator("mode", mode="before")
    @classmethod
    def validate_mode(cls, value: Any) -> str:
        return validate_research_token("mode", value, RESEARCH_MODES)

    @field_validator("stop_criteria", mode="before")
    @classmethod
    def clean_stop_criteria(cls, value: Any) -> list[str]:
        return clean_string_list(value)


class ResearchStep(BaseModel):
    """Application-owned contract for one action inside a research run."""

    id: UUID | None = None
    run_id: UUID
    step_type: str
    status: str = "completed"
    title: str = ""
    query: str = ""
    url: str = ""
    rationale: str = ""
    input: dict[str, Any] = Field(default_factory=dict)
    output: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None
    duration_ms: int = Field(default=0, ge=0)
    created_at: datetime | None = None
    updated_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)

    @field_validator("step_type", mode="before")
    @classmethod
    def validate_step_type(cls, value: Any) -> str:
        return validate_research_token("step_type", value, RESEARCH_STEP_TYPES)

    @field_validator("status", mode="before")
    @classmethod
    def validate_status(cls, value: Any) -> str:
        return validate_research_token("status", value, RESEARCH_STEP_STATUSES)

    @field_validator("title", "query", "url", "rationale", mode="before")
    @classmethod
    def clean_optional_text(cls, value: Any) -> str:
        return normalize_text(value)


class ResearchEvidence(BaseModel):
    """Evidence belongs to a research run, never to long-term memory."""

    id: UUID | None = None
    run_id: UUID
    step_id: UUID | None = None
    source_type: str = "web"
    source_title: str = ""
    source_url: str = ""
    claim: str
    excerpt: str = ""
    quality: str = "unknown"
    relevance: int = Field(default=3, ge=1, le=5)
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime | None = None
    updated_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)

    @field_validator("source_type", mode="before")
    @classmethod
    def validate_source_type(cls, value: Any) -> str:
        return validate_research_token("source_type", value, EVIDENCE_SOURCE_TYPES)

    @field_validator("quality", mode="before")
    @classmethod
    def validate_quality(cls, value: Any) -> str:
        return validate_research_token("quality", value, EVIDENCE_QUALITIES)

    @field_validator("claim", mode="before")
    @classmethod
    def clean_claim(cls, value: Any) -> str:
        text = normalize_text(value)
        if not text:
            raise ValueError("claim cannot be empty")
        return text

    @field_validator("source_title", "source_url", "excerpt", mode="before")
    @classmethod
    def clean_optional_text(cls, value: Any) -> str:
        return normalize_text(value)


class ResearchStateSnapshot(BaseModel):
    """Structured research state snapshot for limited-context continuation."""

    id: UUID | None = None
    run_id: UUID
    step_id: UUID | None = None
    objective: str
    status: str = "active"
    subquestions: list[str] = Field(default_factory=list)
    known_facts: list[str] = Field(default_factory=list)
    gaps: list[str] = Field(default_factory=list)
    conflicts: list[str] = Field(default_factory=list)
    exhausted_queries: list[str] = Field(default_factory=list)
    next_actions: list[str] = Field(default_factory=list)
    evidence_ids: list[UUID] = Field(default_factory=list)
    budget: dict[str, Any] = Field(default_factory=dict)
    stop_criteria: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)

    @field_validator("objective", mode="before")
    @classmethod
    def clean_objective(cls, value: Any) -> str:
        text = normalize_text(value)
        if not text:
            raise ValueError("objective cannot be empty")
        return text

    @field_validator("status", mode="before")
    @classmethod
    def validate_status(cls, value: Any) -> str:
        return validate_research_token("status", value, RESEARCH_RUN_STATUSES)

    @field_validator(
        "subquestions",
        "known_facts",
        "gaps",
        "conflicts",
        "exhausted_queries",
        "next_actions",
        "stop_criteria",
        mode="before",
    )
    @classmethod
    def clean_text_lists(cls, value: Any) -> list[str]:
        return clean_string_list(value)


class ResearchStateResult(BaseModel):
    """Full structured state returned to the agent and API clients."""

    run: ResearchRun
    state: ResearchStateSnapshot
    steps: list[ResearchStep] = Field(default_factory=list)
    evidence: list[ResearchEvidence] = Field(default_factory=list)
    provider_sources: list[str] = Field(default_factory=list)


class ResearchRunListResult(BaseModel):
    user_id: UUID
    runs: list[ResearchRun] = Field(default_factory=list)
    total: int = 0
    limit: int = 50
    offset: int = 0
    provider_sources: list[str] = Field(default_factory=list)
