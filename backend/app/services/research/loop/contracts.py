from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from app.services.research.contracts import normalize_text
from app.services.research.source_acquisition import ResearchSourceRecord
from app.services.research.source_extraction import RejectedResearchSourceDocument


RESEARCH_LOOP_CONTRACT_VERSION = "research-loop-v1"

ResearchGapCode = Literal[
    "missing_recency_evidence",
    "missing_review_evidence",
    "missing_book_evidence",
    "insufficient_independent_sources",
    "no_publishable_evidence",
]
ResearchLoopStopReason = Literal[
    "continue",
    "evidence_satisfied",
    "search_budget_exhausted",
    "previous_round_satisfied",
]


class ResearchLoopBudget(BaseModel):
    max_search_rounds: int = Field(default=2, ge=1, le=3)
    max_results_per_round: int = Field(default=5, ge=1, le=10)
    max_records_per_round: int = Field(default=3, ge=1, le=5)
    min_independent_sources: int = Field(default=1, ge=1, le=5)


class ResearchSearchTask(BaseModel):
    result_mode: str = "research_search_task"
    contract_version: str = RESEARCH_LOOP_CONTRACT_VERSION
    round_index: int = Field(ge=1, le=3)
    objective: str
    purpose: str = "initial_evidence"
    query: str
    should_search: bool = True
    target_gaps: list[str] = Field(default_factory=list)
    exhausted_queries: list[str] = Field(default_factory=list)
    max_results: int = Field(default=5, ge=1, le=10)
    detail: str = "deep"
    time_range: str | None = None
    include_domains: list[str] = Field(default_factory=list)
    exclude_domains: list[str] = Field(default_factory=list)
    include_url_prefixes: list[str] = Field(default_factory=list)
    language: str = ""
    category: str = "general"
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("objective", "purpose", "query", mode="before")
    @classmethod
    def clean_text(cls, value: Any) -> str:
        return normalize_text(value)

    def tool_arguments(self) -> dict[str, Any]:
        return {
            "query": self.query,
            "max_results": self.max_results,
            "detail": self.detail,
            "time_range": self.time_range,
            "include_domains": list(self.include_domains),
            "exclude_domains": list(self.exclude_domains),
            "include_url_prefixes": list(self.include_url_prefixes),
            "language": self.language,
            "category": self.category,
            "round_index": self.round_index,
        }


class ResearchRoundSources(BaseModel):
    result_mode: str = "research_round_sources"
    contract_version: str = RESEARCH_LOOP_CONTRACT_VERSION
    status: str = "completed"
    round_index: int = Field(ge=1, le=3)
    executed: bool = True
    task: ResearchSearchTask
    provider: str = ""
    provider_status: str = ""
    provider_error_type: str = ""
    error: str = ""
    source_records: list[ResearchSourceRecord] = Field(default_factory=list)
    rejected_documents: list[RejectedResearchSourceDocument] = Field(
        default_factory=list
    )
    source_count: int = 0
    publishable_source_count: int = 0
    rejection_reason_codes: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ResearchGapAssessment(BaseModel):
    result_mode: str = "research_gap_assessment"
    contract_version: str = RESEARCH_LOOP_CONTRACT_VERSION
    status: str = "completed"
    round_index: int = Field(ge=1, le=3)
    gaps: list[str] = Field(default_factory=list)
    gap_descriptions: list[str] = Field(default_factory=list)
    satisfied: bool = False
    should_continue: bool = False
    stop_reason: ResearchLoopStopReason
    accepted_record_count: int = 0
    independent_source_count: int = 0
    exhausted_queries: list[str] = Field(default_factory=list)
    next_actions: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
