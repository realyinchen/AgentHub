from __future__ import annotations

from typing import Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)


class ExternalCapabilityInput(BaseModel):
    model_config = ConfigDict(extra="forbid")


class WeatherGetInput(ExternalCapabilityInput):
    location: str = Field(min_length=1, max_length=120)
    date: str = Field(
        default="today",
        min_length=1,
        max_length=32,
        description="today, tomorrow, or an ISO calendar date",
    )
    units: Literal["metric", "imperial"] = "metric"
    language: str = Field(default="zh-CN", max_length=24)

    @field_validator("location", "date", "language", mode="before")
    @classmethod
    def normalize_text(cls, value: Any) -> str:
        return " ".join(str(value or "").split())


class WebSearchInput(ExternalCapabilityInput):
    query: str = Field(min_length=1, max_length=300)
    max_results: int = Field(default=5, ge=1, le=10)
    detail: Literal["standard", "deep"] = "standard"
    time_range: Literal["day", "week", "month", "year"] | None = None
    include_domains: list[str] = Field(default_factory=list, max_length=20)
    exclude_domains: list[str] = Field(default_factory=list, max_length=20)
    language: str = Field(default="", max_length=24)
    category: Literal["general", "news"] = "general"

    @field_validator("query", "language", mode="before")
    @classmethod
    def normalize_text(cls, value: Any) -> str:
        return " ".join(str(value or "").split())

    @field_validator("include_domains", "exclude_domains", mode="before")
    @classmethod
    def normalize_domains(cls, value: Any) -> list[str]:
        values = value.split(",") if isinstance(value, str) else value or []
        cleaned = [
            str(item or "")
            .strip()
            .lower()
            .removeprefix("https://")
            .removeprefix("http://")
            .split("/", 1)[0]
            for item in values
        ]
        return list(dict.fromkeys(item for item in cleaned if item))


class BookSearchInput(ExternalCapabilityInput):
    query: str = Field(min_length=1, max_length=300)
    limit: int = Field(default=5, ge=1, le=10)
    language: str = Field(default="", max_length=24)
    genres: list[str] = Field(default_factory=list, max_length=10)
    authors: list[str] = Field(default_factory=list, max_length=10)
    audience: str = Field(default="", max_length=120)
    publication_year_from: int | None = Field(
        default=None,
        ge=1000,
        le=2200,
    )
    publication_year_to: int | None = Field(
        default=None,
        ge=1000,
        le=2200,
    )

    @field_validator("query", "language", "audience", mode="before")
    @classmethod
    def normalize_text(cls, value: Any) -> str:
        return " ".join(str(value or "").split())

    @field_validator("genres", "authors", mode="before")
    @classmethod
    def normalize_lists(cls, value: Any) -> list[str]:
        values = value if isinstance(value, list) else [value] if value else []
        cleaned = [" ".join(str(item or "").split()) for item in values]
        return list(dict.fromkeys(item for item in cleaned if item))

    @model_validator(mode="after")
    def validate_year_range(self) -> "BookSearchInput":
        if (
            self.publication_year_from is not None
            and self.publication_year_to is not None
            and self.publication_year_from > self.publication_year_to
        ):
            raise ValueError("publication year range is reversed")
        return self


class ResearchStartInput(ExternalCapabilityInput):
    objective: str = Field(min_length=1, max_length=2_000)
    mode: Literal["deep_search", "deep_research"] = "deep_search"
    subquestions: list[str] = Field(default_factory=list, max_length=8)
    constraints: list[str] = Field(default_factory=list, max_length=10)
    max_sources: int = Field(default=8, ge=3, le=20)
    max_rounds: int = Field(default=2, ge=1, le=3)
    time_range: Literal["day", "week", "month", "year"] | None = None
    language: str = Field(default="", max_length=24)

    @field_validator("objective", "language", mode="before")
    @classmethod
    def normalize_text(cls, value: Any) -> str:
        return " ".join(str(value or "").split())

    @field_validator("subquestions", "constraints", mode="before")
    @classmethod
    def normalize_lists(cls, value: Any) -> list[str]:
        values = value if isinstance(value, list) else [value] if value else []
        cleaned = [" ".join(str(item or "").split()) for item in values]
        return list(dict.fromkeys(item for item in cleaned if item))


class ExternalEvidenceSource(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(default="", max_length=300)
    url: str = Field(max_length=2_000)
    snippet: str = Field(default="", max_length=1_000)
    published_date: str = Field(default="", max_length=64)


class WeatherEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    result_mode: Literal["weather_evidence"] = "weather_evidence"
    status: Literal["ok", "empty_result", "unavailable"]
    location: str
    date: str
    units: Literal["metric", "imperial"]
    sources: list[ExternalEvidenceSource] = Field(
        default_factory=list,
        max_length=3,
    )
    error: str = Field(default="", max_length=120)


class WebEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    result_mode: Literal["web_evidence"] = "web_evidence"
    status: Literal["ok", "empty_result", "unavailable"]
    query: str
    sources: list[ExternalEvidenceSource] = Field(
        default_factory=list,
        max_length=10,
    )
    error: str = Field(default="", max_length=120)


class BookEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    result_mode: Literal["book_evidence"] = "book_evidence"
    status: Literal["ok", "empty_result", "unavailable"]
    query: str
    sources: list[ExternalEvidenceSource] = Field(
        default_factory=list,
        max_length=10,
    )
    error: str = Field(default="", max_length=120)


class ResearchReportEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    result_mode: Literal[
        "research_report_evidence"
    ] = "research_report_evidence"
    status: Literal["ok", "empty_result", "unavailable"]
    objective: str
    findings: list[str] = Field(default_factory=list, max_length=20)
    sources: list[ExternalEvidenceSource] = Field(
        default_factory=list,
        max_length=20,
    )
    limitations: list[str] = Field(default_factory=list, max_length=10)
    error: str = Field(default="", max_length=120)


__all__ = [
    "BookEvidence",
    "BookSearchInput",
    "ExternalCapabilityInput",
    "ExternalEvidenceSource",
    "ResearchReportEvidence",
    "ResearchStartInput",
    "WebEvidence",
    "WebSearchInput",
    "WeatherEvidence",
    "WeatherGetInput",
]
