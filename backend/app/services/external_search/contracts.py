from __future__ import annotations

from typing import Any, Literal, Protocol

from pydantic import BaseModel, Field, field_validator


SearchDetail = Literal["standard", "deep"]
SearchOutcome = Literal["found", "empty", "unavailable"]
SearchCategory = Literal["general", "news"]


def _clean_domain(value: Any) -> str:
    return (
        str(value or "")
        .strip()
        .lower()
        .removeprefix("https://")
        .removeprefix("http://")
        .split("/", 1)[0]
    )


class SearchRequest(BaseModel):
    """The complete business input accepted by every search provider."""

    query: str = Field(min_length=1, max_length=300)
    max_results: int = Field(default=5, ge=1, le=10)
    detail: SearchDetail = "standard"
    time_range: Literal["day", "week", "month", "year"] | None = None
    include_domains: list[str] = Field(default_factory=list, max_length=300)
    exclude_domains: list[str] = Field(default_factory=list, max_length=150)
    include_url_prefixes: list[str] = Field(default_factory=list, max_length=20)
    language: str = ""
    zone: Literal["cn", "intl"] | None = None
    category: SearchCategory = "general"
    round_index: int = Field(default=1, ge=1, le=3)

    @field_validator("query", mode="before")
    @classmethod
    def clean_query(cls, value: Any) -> str:
        return " ".join(str(value or "").split())

    @field_validator("include_domains", "exclude_domains", mode="before")
    @classmethod
    def clean_domains(cls, value: Any) -> list[str]:
        values = value.split(",") if isinstance(value, str) else value or []
        cleaned = [_clean_domain(item) for item in values]
        return list(dict.fromkeys(item for item in cleaned if item))

    @field_validator("include_url_prefixes", mode="before")
    @classmethod
    def clean_url_prefixes(cls, value: Any) -> list[str]:
        values = value if isinstance(value, list) else [value] if value else []
        cleaned = [str(item or "").strip() for item in values]
        return list(dict.fromkeys(item for item in cleaned if item))


class SearchHit(BaseModel):
    title: str = ""
    url: str
    snippet: str = ""
    content: str = ""
    published_date: str = ""
    provider: str
    score: float | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class SearchAttempt(BaseModel):
    provider: str
    outcome: SearchOutcome
    duration_ms: int = Field(default=0, ge=0)
    error_type: str = ""
    error: str = ""
    upstream_request_id: str = ""


class SearchResult(BaseModel):
    """A completed gateway execution, including empty and unavailable outcomes."""

    execution_status: Literal["completed"] = "completed"
    outcome: SearchOutcome
    provider: str = ""
    query: str
    effective_query: str = ""
    hits: list[SearchHit] = Field(default_factory=list)
    attempts: list[SearchAttempt] = Field(default_factory=list)
    error: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)


class SearchProvider(Protocol):
    name: str

    async def search(self, request: SearchRequest) -> SearchResult:
        ...
