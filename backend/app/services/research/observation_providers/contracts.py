from __future__ import annotations

from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator

from app.services.research.contracts import (
    EVIDENCE_QUALITIES,
    EVIDENCE_SOURCE_TYPES,
    RESEARCH_STEP_STATUSES,
    normalize_research_token,
    normalize_text,
    validate_research_token,
)


OBSERVATION_PROVIDER_STATUSES = frozenset(
    {"completed", "empty_result", "timeout", "failed", "skipped"}
)
PROVIDER_STATUS_TO_RESEARCH_STEP_STATUS = {
    "ok": "completed",
    "success": "completed",
    "completed": "completed",
    "empty": "empty_result",
    "empty_result": "empty_result",
    "no_result": "empty_result",
    "no_results": "empty_result",
    "timeout": "timeout",
    "timed_out": "timeout",
    "failed": "failed",
    "failure": "failed",
    "error": "failed",
    "hard_error": "failed",
    "rate_limited": "failed",
    "skipped": "skipped",
}


def map_provider_status(value: Any) -> str:
    """Map provider-native status text to the Research step status contract."""

    token = normalize_research_token(value)
    mapped = PROVIDER_STATUS_TO_RESEARCH_STEP_STATUS.get(token, "failed")
    return validate_research_token("status", mapped, RESEARCH_STEP_STATUSES)


class ResearchObservation(BaseModel):
    """App-owned normalized observation returned by provider adapters."""

    source_type: str = "web"
    source_title: str = ""
    source_url: str = ""
    claim: str
    excerpt: str = ""
    quality: str = "unknown"
    relevance: int = Field(default=3, ge=1, le=5)
    metadata: dict[str, Any] = Field(default_factory=dict)

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


class ObservationProviderRequest(BaseModel):
    """Input envelope for observation providers."""

    run_id: UUID
    query: str
    subquestion: str = ""
    rationale: str = ""
    max_results: int = Field(default=5, ge=1, le=20)
    seed_observations: list[ResearchObservation] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("query", mode="before")
    @classmethod
    def clean_query(cls, value: Any) -> str:
        text = normalize_text(value)
        if not text:
            raise ValueError("query cannot be empty")
        return text

    @field_validator("subquestion", "rationale", mode="before")
    @classmethod
    def clean_optional_text(cls, value: Any) -> str:
        return normalize_text(value)


class ObservationProviderResult(BaseModel):
    """Provider output envelope with app-owned status and observation fields."""

    provider_name: str
    query: str
    status: str
    observations: list[ResearchObservation] = Field(default_factory=list)
    error: str | None = None
    duration_ms: int = Field(default=0, ge=0)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("provider_name", "query", mode="before")
    @classmethod
    def clean_required_text(cls, value: Any) -> str:
        text = normalize_text(value)
        if not text:
            raise ValueError("provider_name and query cannot be empty")
        return text

    @field_validator("status", mode="before")
    @classmethod
    def validate_status(cls, value: Any) -> str:
        status = map_provider_status(value)
        if status not in OBSERVATION_PROVIDER_STATUSES:
            raise ValueError("status is not allowed for observation provider result")
        return status

    @field_validator("error", mode="before")
    @classmethod
    def clean_error(cls, value: Any) -> str | None:
        text = normalize_text(value)
        return text or None

    @model_validator(mode="after")
    def validate_provider_metadata(self) -> "ObservationProviderResult":
        for observation in self.observations:
            provider_source = observation.metadata.get("provider_source")
            provider_raw = observation.metadata.get("provider_raw")
            if not provider_source:
                raise ValueError("observation metadata.provider_source is required")
            if provider_raw is None:
                raise ValueError("observation metadata.provider_raw is required")
        return self
