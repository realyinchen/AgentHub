from __future__ import annotations

from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.services.research.contracts import clean_string_list, normalize_text


RESEARCH_BRIEF_CONTRACT_VERSION = "research-brief-v1"
RESEARCH_SYNTHESIS_CONTRACT_VERSION = "research-synthesis-v1"
PUBLISHED_RESEARCH_ANSWER_CONTRACT_VERSION = "research-published-answer-v1"


class ResearchFinding(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=100)
    summary: str = Field(min_length=1, max_length=280)
    why_it_matters: str = Field(default="", max_length=180)
    caveat: str = Field(default="", max_length=180)
    source_ids: list[str] = Field(min_length=1, max_length=4)

    @field_validator(
        "title",
        "summary",
        "why_it_matters",
        "caveat",
        mode="before",
    )
    @classmethod
    def clean_text(cls, value: Any) -> str:
        return normalize_text(value)

    @field_validator("source_ids", mode="before")
    @classmethod
    def clean_sources(cls, value: Any) -> list[str]:
        return clean_string_list(value if isinstance(value, list) else [])


class ResearchBrief(BaseModel):
    model_config = ConfigDict(extra="forbid")

    contract_version: str = RESEARCH_BRIEF_CONTRACT_VERSION
    language: Literal["zh-CN", "en"] = "zh-CN"
    overview: str = Field(default="", max_length=420)
    findings: list[ResearchFinding] = Field(default_factory=list, max_length=5)
    limitations: list[str] = Field(default_factory=list, max_length=5)

    @field_validator("overview", mode="before")
    @classmethod
    def clean_overview(cls, value: Any) -> str:
        return normalize_text(value)

    @field_validator("limitations", mode="before")
    @classmethod
    def clean_limitations(cls, value: Any) -> list[str]:
        return [
            item[:180]
            for item in clean_string_list(
                value if isinstance(value, list) else []
            )
        ][:5]


class ResearchSynthesisResult(BaseModel):
    result_mode: str = "research_synthesis"
    contract_version: str = RESEARCH_SYNTHESIS_CONTRACT_VERSION
    run_id: UUID
    objective: str
    status: Literal["synthesized", "fallback", "empty"]
    provider: str
    model_id: str = ""
    brief: ResearchBrief
    admitted_evidence_ids: list[str] = Field(default_factory=list)
    error: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)


class PublishedResearchSource(BaseModel):
    source_id: str
    title: str = ""
    url: str = ""
    published_date: str = ""
    source_class: str = "unknown"


class PublishedResearchAnswer(BaseModel):
    result_mode: str = "research_published_answer"
    contract_version: str = PUBLISHED_RESEARCH_ANSWER_CONTRACT_VERSION
    run_id: UUID
    objective: str
    answer_status: Literal[
        "verified",
        "partial_with_limitations",
        "blocked_no_publishable_evidence",
    ]
    language: Literal["zh-CN", "en"] = "zh-CN"
    answer: str
    brief: ResearchBrief
    sources: list[PublishedResearchSource] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
