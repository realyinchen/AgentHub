from __future__ import annotations

from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from app.services.research.contracts import (
    EVIDENCE_QUALITIES,
    EVIDENCE_SOURCE_TYPES,
    ResearchEvidence,
    clean_string_list,
    normalize_text,
    validate_research_token,
)


CLAIM_ADMISSION_STATUSES = frozenset({"admitted", "rejected", "uncertain"})
CLAIM_ADMISSION_REASONS = frozenset(
    {
        "supported_by_evidence",
        "missing_evidence",
        "unknown_evidence",
        "insufficient_sources",
        "missing_source_metadata",
        "low_quality_evidence",
        "unknown_quality_evidence",
        "blocking_gap",
        "unresolved_conflict",
        "stop_criteria_not_met",
        "budget_exhausted",
        "explicit_uncertainty",
        "claim_too_short",
        "claim_too_long",
        "claim_not_atomic",
        "keyword_stuffing",
        "query_irrelevant",
        "marketplace_source",
        "insufficient_independent_sources",
        "missing_recency_evidence",
        "missing_review_evidence",
        "missing_book_evidence",
    }
)


def _validate_reason_code(value: Any) -> str:
    return validate_research_token("reason_code", value, CLAIM_ADMISSION_REASONS)


class EvidenceReference(BaseModel):
    """Verifier-owned projection of a persisted ResearchEvidence row."""

    id: UUID
    source_type: str = "web"
    source_title: str = ""
    source_url: str = ""
    published_date: str = ""
    quality: str = "unknown"
    relevance: int = Field(default=3, ge=1, le=5)
    source_class: str = "unknown"
    provenance_valid: bool = False
    content_quality: float = Field(default=0.0, ge=0.0, le=1.0)
    query_relevance: float = Field(default=0.0, ge=0.0, le=1.0)
    publishable: bool = False

    @field_validator("source_type", mode="before")
    @classmethod
    def validate_source_type(cls, value: Any) -> str:
        return validate_research_token("source_type", value, EVIDENCE_SOURCE_TYPES)

    @field_validator("quality", mode="before")
    @classmethod
    def validate_quality(cls, value: Any) -> str:
        return validate_research_token("quality", value, EVIDENCE_QUALITIES)

    @field_validator(
        "source_title",
        "source_url",
        "published_date",
        mode="before",
    )
    @classmethod
    def clean_optional_text(cls, value: Any) -> str:
        return normalize_text(value)


class ClaimForVerification(BaseModel):
    """One candidate claim proposed by aggregation for verifier admission."""

    claim: str
    evidence_ids: list[UUID] = Field(default_factory=list)
    quality: str = "unknown"
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("claim", mode="before")
    @classmethod
    def clean_claim(cls, value: Any) -> str:
        text = normalize_text(value)
        if not text:
            raise ValueError("claim cannot be empty")
        return text

    @field_validator("quality", mode="before")
    @classmethod
    def validate_quality(cls, value: Any) -> str:
        return validate_research_token("quality", value, EVIDENCE_QUALITIES)


class ClaimAdmissionDecision(BaseModel):
    """Verifier decision for one candidate claim."""

    claim: str
    status: str
    evidence_ids: list[UUID] = Field(default_factory=list)
    evidence: list[EvidenceReference] = Field(default_factory=list)
    quality: str = "unknown"
    reason_codes: list[str] = Field(default_factory=list)
    explanation: str = ""
    provenance_valid: bool = False
    content_quality: float = Field(default=0.0, ge=0.0, le=1.0)
    query_relevance: float = Field(default=0.0, ge=0.0, le=1.0)
    corroborated: bool = False
    publishable: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("claim", mode="before")
    @classmethod
    def clean_claim(cls, value: Any) -> str:
        text = normalize_text(value)
        if not text:
            raise ValueError("claim cannot be empty")
        return text

    @field_validator("status", mode="before")
    @classmethod
    def validate_status(cls, value: Any) -> str:
        return validate_research_token(
            "status",
            value,
            CLAIM_ADMISSION_STATUSES,
        )

    @field_validator("quality", mode="before")
    @classmethod
    def validate_quality(cls, value: Any) -> str:
        return validate_research_token("quality", value, EVIDENCE_QUALITIES)

    @field_validator("reason_codes", mode="before")
    @classmethod
    def clean_reason_codes(cls, values: list[Any] | None) -> list[str]:
        cleaned: list[str] = []
        seen: set[str] = set()
        for value in values or []:
            reason = _validate_reason_code(value)
            if reason not in seen:
                seen.add(reason)
                cleaned.append(reason)
        return cleaned

    @field_validator("explanation", mode="before")
    @classmethod
    def clean_explanation(cls, value: Any) -> str:
        return normalize_text(value)


class VerifierAdmissionInput(BaseModel):
    """Code-level verifier input assembled from ResearchOrchestrator state."""

    run_id: UUID
    objective: str = ""
    candidate_claims: list[ClaimForVerification] = Field(default_factory=list)
    evidence: list[ResearchEvidence] = Field(default_factory=list)
    blocking_gaps: list[str] = Field(default_factory=list)
    conflicts: list[str] = Field(default_factory=list)
    exhausted_queries: list[str] = Field(default_factory=list)
    budget: dict[str, Any] = Field(default_factory=dict)
    stop_criteria: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("blocking_gaps", "conflicts", "exhausted_queries", "stop_criteria", mode="before")
    @classmethod
    def clean_text_lists(cls, value: Any) -> list[str]:
        return clean_string_list(value)

    @field_validator("objective", mode="before")
    @classmethod
    def clean_objective(cls, value: Any) -> str:
        return normalize_text(value)


class VerifierAdmissionResult(BaseModel):
    """Complete verifier decision set for one research run."""

    run_id: UUID
    decisions: list[ClaimAdmissionDecision] = Field(default_factory=list)
    admitted_claims: list[ClaimAdmissionDecision] = Field(default_factory=list)
    rejected_claims: list[ClaimAdmissionDecision] = Field(default_factory=list)
    uncertain_claims: list[ClaimAdmissionDecision] = Field(default_factory=list)
    blocking_gaps: list[str] = Field(default_factory=list)
    conflicts: list[str] = Field(default_factory=list)
    ready_for_final_answer: bool = False
    can_finalize_with_uncertainty: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)
