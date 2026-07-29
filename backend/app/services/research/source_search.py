from __future__ import annotations

import time
from html import unescape
from typing import Any

from pydantic import BaseModel, Field, field_validator

from app.services.external_search import SearchRequest, get_search_gateway
from app.services.research.contracts import (
    EVIDENCE_QUALITIES,
    EVIDENCE_SOURCE_TYPES,
    normalize_research_token,
    normalize_text,
)
from app.services.research.source_extraction import (
    ResearchSourceExtractionResult,
    extract_research_source_records,
)


RESEARCH_SOURCE_SEARCH_CONTRACT_VERSION = "research-source-search-v1"


class ResearchSourceDocument(BaseModel):
    source_type: str = "web"
    source_title: str = ""
    source_url: str = ""
    content: str = ""
    quality: str = "unknown"
    relevance: int = Field(default=3, ge=1, le=5)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("source_type", mode="before")
    @classmethod
    def validate_source_type(cls, value: Any) -> str:
        return _source_type(value)

    @field_validator("quality", mode="before")
    @classmethod
    def validate_quality(cls, value: Any) -> str:
        return _quality(value)

    @field_validator("source_title", "source_url", "content", mode="before")
    @classmethod
    def clean_text(cls, value: Any) -> str:
        return normalize_text(value)


class ResearchSourceSearchProviderResult(BaseModel):
    provider_name: str
    provider_query: str
    status: str
    documents: list[ResearchSourceDocument] = Field(default_factory=list)
    error: str | None = None
    duration_ms: int = 0
    metadata: dict[str, Any] = Field(default_factory=dict)


class ResearchSourceSearchResult(BaseModel):
    result_mode: str = "research_source_search"
    contract_version: str = RESEARCH_SOURCE_SEARCH_CONTRACT_VERSION
    status: str
    query: str
    subquestion: str = ""
    provider_name: str
    provider_query: str
    source_documents: list[ResearchSourceDocument] = Field(default_factory=list)
    extraction: ResearchSourceExtractionResult
    document_count: int = 0
    extracted_count: int = 0
    error: str | None = None
    duration_ms: int = 0
    metadata: dict[str, Any] = Field(default_factory=dict)


async def search_research_source_documents(
    *,
    query: str,
    subquestion: str = "",
    limit: int = 5,
    provider_query: str = "",
    provider_source: str = "external_search",
    include_extraction: bool = True,
    metadata: dict[str, Any] | None = None,
) -> ResearchSourceSearchResult:
    """Search for research source documents and project them into app fields.

    This function may perform an external search provider call, but it remains
    read-only for app state: it does not write research state, evidence,
    long-term memory, recommendation events, or provider state. The nested
    extraction is also read-only; later tools decide whether to record trace or
    admit evidence.
    """

    normalized_query = normalize_text(query)
    normalized_subquestion = normalize_text(subquestion)
    del provider_source
    max_results = max(1, min(int(limit or 5), 10))

    provider_result = await search_external_research_documents(
        query=normalized_query,
        subquestion=normalized_subquestion,
        limit=max_results,
        provider_query=provider_query,
    )

    extraction = extract_research_source_records(
        query=normalized_query,
        subquestion=normalized_subquestion,
        documents=[document.model_dump(mode="json") for document in provider_result.documents],
        provider_source=f"{provider_result.provider_name}_source_search",
        metadata={
            **(metadata or {}),
            "source_search": {
                "contract_version": RESEARCH_SOURCE_SEARCH_CONTRACT_VERSION,
                "provider_name": provider_result.provider_name,
                "provider_query": provider_result.provider_query,
            },
        },
    )
    if not include_extraction:
        extraction = extraction.model_copy(
            update={
                "source_records": [],
                "observation_batch": extraction.observation_batch.model_copy(
                    update={"observations": [], "observation_count": 0}
                ),
                "extracted_count": 0,
            }
        )

    return ResearchSourceSearchResult(
        status=_result_status(provider_result.status, extraction.extracted_count),
        query=normalized_query,
        subquestion=normalized_subquestion,
        provider_name=provider_result.provider_name,
        provider_query=provider_result.provider_query,
        source_documents=provider_result.documents,
        extraction=extraction,
        document_count=len(provider_result.documents),
        extracted_count=extraction.extracted_count,
        error=provider_result.error,
        duration_ms=provider_result.duration_ms,
        metadata={
            **(metadata or {}),
            "writes_research_state": False,
            "writes_evidence": False,
            "writes_long_term_memory": False,
            "writes_recommendation_events": False,
            "external_call": True,
            "provider_source": provider_result.provider_name,
            "provider_status": provider_result.status,
            "provider": provider_result.metadata,
        },
    )


async def search_external_research_documents(
    *,
    query: str,
    subquestion: str = "",
    limit: int = 5,
    provider_query: str = "",
) -> ResearchSourceSearchProviderResult:
    normalized_query = normalize_text(query)
    search_query = normalize_text(provider_query) or _build_provider_query(
        normalized_query,
        subquestion,
    )
    started_at = time.perf_counter()
    result = await get_search_gateway().search(
        SearchRequest(
            query=search_query,
            max_results=max(1, min(limit, 10)),
            detail="deep",
        )
    )
    documents = _documents_from_search_results(
        results=[
            {
                "title": hit.title,
                "url": hit.url,
                "snippet": hit.snippet or hit.content,
            }
            for hit in result.hits
        ],
        query=normalized_query,
        provider_query=search_query,
        provider_name=result.provider or "external_search",
        limit=limit,
    )
    if documents:
        status = "ok"
    elif result.outcome == "empty":
        status = "empty_result"
    elif any(item.error_type == "timeout" for item in result.attempts):
        status = "timeout"
    else:
        status = "hard_error"
    return ResearchSourceSearchProviderResult(
        provider_name=result.provider or "external_search",
        provider_query=search_query,
        status=status,
        documents=documents,
        error=result.error or None,
        duration_ms=_duration_ms(started_at),
        metadata={
            "provider_source": result.provider or "external_search",
            "provider_raw": {
                "outcome": result.outcome,
                "attempts": [
                    attempt.model_dump(mode="json")
                    for attempt in result.attempts
                ],
                "accepted_document_count": len(documents),
            },
        },
    )


async def search_duckduckgo_research_documents(
    *,
    query: str,
    subquestion: str = "",
    limit: int = 5,
    provider_query: str = "",
) -> ResearchSourceSearchProviderResult:
    """Compatibility alias; network access is owned by SearchGateway."""

    return await search_external_research_documents(
        query=query,
        subquestion=subquestion,
        limit=limit,
        provider_query=provider_query,
    )


def _documents_from_search_results(
    *,
    results: list[dict[str, str]],
    query: str,
    provider_query: str,
    provider_name: str,
    limit: int,
) -> list[ResearchSourceDocument]:
    documents: list[ResearchSourceDocument] = []
    seen_urls: set[str] = set()
    for index, item in enumerate(results):
        url = normalize_text(item.get("url"))
        title = normalize_text(item.get("title"))
        snippet = normalize_text(item.get("snippet"))
        if not url or url in seen_urls:
            continue
        seen_urls.add(url)
        content = _document_content(title, snippet)
        documents.append(
            ResearchSourceDocument(
                source_type="web",
                source_title=title,
                source_url=url,
                content=content,
                quality="unknown",
                relevance=_relevance_for_search_result(query, title, snippet),
                metadata={
                    "provider_source": provider_name,
                    "provider_raw": {
                        "title": title,
                        "url": url,
                        "snippet": snippet,
                        "query": query,
                        "provider_query": provider_query,
                        "index": index,
                    },
                },
            )
        )
        if len(documents) >= max(1, min(limit, 10)):
            break
    return documents


def _document_content(title: str, snippet: str) -> str:
    if title and snippet:
        return _compact_text(f"{title}. {snippet}")
    return snippet or title


def _relevance_for_search_result(query: str, title: str, snippet: str) -> int:
    terms = set(_terms(query))
    if not terms:
        return 3
    haystack = f"{title} {snippet}".lower()
    matches = sum(1 for term in terms if term in haystack)
    if matches <= 0:
        return 2
    if matches >= 3:
        return 5
    return 3 + min(matches, 2)


def _terms(text: str) -> list[str]:
    return [
        chunk
        for chunk in normalize_text(text).lower().replace("/", " ").split()
        if len(chunk) >= 3
    ]


def _build_provider_query(query: str, subquestion: str) -> str:
    if "site:" in query:
        return query
    parts = [query]
    if subquestion and subquestion.lower() not in query.lower():
        parts.append(subquestion)
    return _compact_text(" ".join(parts))


def _result_status(provider_status: str, extracted_count: int) -> str:
    if provider_status in {"timeout", "hard_error", "failed"}:
        return provider_status
    if extracted_count > 0:
        return "ok"
    if provider_status == "ok":
        return "no_extractable_claims"
    return provider_status or "empty_result"


def _compact_text(text: str) -> str:
    return " ".join(unescape(str(text or "")).split()).strip()

def _source_type(value: Any) -> str:
    token = normalize_research_token(value or "web")
    return token if token in EVIDENCE_SOURCE_TYPES else "other"


def _quality(value: Any) -> str:
    token = normalize_research_token(value or "unknown")
    return token if token in EVIDENCE_QUALITIES else "unknown"


def _duration_ms(started_at: float) -> int:
    return max(0, int((time.perf_counter() - started_at) * 1000))
