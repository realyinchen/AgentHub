from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


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


__all__ = [
    "ExternalCapabilityInput",
    "ExternalEvidenceSource",
    "WebEvidence",
    "WebSearchInput",
    "WeatherEvidence",
    "WeatherGetInput",
]
