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


__all__ = [
    "ExternalCapabilityInput",
    "ExternalEvidenceSource",
    "WeatherEvidence",
    "WeatherGetInput",
]

