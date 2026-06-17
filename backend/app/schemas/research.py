from __future__ import annotations

from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field

from app.services.research.contracts import (
    ResearchEvidence,
    ResearchRun,
    ResearchRunListResult,
    ResearchStateResult,
)


class ResearchStartRequest(BaseModel):
    user_id: UUID
    thread_id: UUID | None = None
    objective: str = Field(..., min_length=1)
    mode: str = "deep_search"
    subquestions: list[str] = Field(default_factory=list)
    gaps: list[str] = Field(default_factory=list)
    next_actions: list[str] = Field(default_factory=list)
    budget: dict[str, Any] = Field(default_factory=dict)
    stop_criteria: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ResearchSearchRequest(BaseModel):
    user_id: UUID
    run_id: UUID
    query: str = Field(..., min_length=1)
    status: str = "completed"
    rationale: str = ""
    results: list[dict[str, Any]] = Field(default_factory=list)
    next_actions: list[str] = Field(default_factory=list)
    duration_ms: int = Field(default=0, ge=0)
    error: str | None = None


class ResearchVisitRequest(BaseModel):
    user_id: UUID
    run_id: UUID
    url: str = Field(..., min_length=1)
    title: str = ""
    status: str = "completed"
    summary: str = ""
    rationale: str = ""
    duration_ms: int = Field(default=0, ge=0)
    error: str | None = None


class ResearchEvidenceRequest(BaseModel):
    user_id: UUID
    run_id: UUID
    source_type: str = "web"
    source_title: str = ""
    source_url: str = ""
    claim: str = Field(..., min_length=1)
    excerpt: str = ""
    quality: str = "unknown"
    relevance: int = Field(default=3, ge=1, le=5)
    metadata: dict[str, Any] = Field(default_factory=dict)
    known_facts: list[str] = Field(default_factory=list)
    gaps: list[str] = Field(default_factory=list)
    conflicts: list[str] = Field(default_factory=list)
    next_actions: list[str] = Field(default_factory=list)


class ResearchStateUpdateRequest(BaseModel):
    user_id: UUID
    run_id: UUID
    subquestions: list[str] | None = None
    known_facts: list[str] | None = None
    gaps: list[str] | None = None
    conflicts: list[str] | None = None
    exhausted_queries: list[str] | None = None
    next_actions: list[str] | None = None
    budget: dict[str, Any] | None = None
    stop_criteria: list[str] | None = None
    metadata: dict[str, Any] | None = None
    replace: bool = False


class ResearchFinishRequest(BaseModel):
    user_id: UUID
    run_id: UUID
    conclusion: str = Field(..., min_length=1)
    status: str = "completed"
    known_facts: list[str] = Field(default_factory=list)
    gaps: list[str] = Field(default_factory=list)
    conflicts: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


__all__ = [
    "ResearchEvidence",
    "ResearchEvidenceRequest",
    "ResearchFinishRequest",
    "ResearchRun",
    "ResearchRunListResult",
    "ResearchSearchRequest",
    "ResearchStartRequest",
    "ResearchStateResult",
    "ResearchStateUpdateRequest",
    "ResearchVisitRequest",
]
