from __future__ import annotations

import logging
import re
import time
from html import unescape
from typing import Any

import aiohttp
from pydantic import BaseModel, Field

from app.services.research.contracts import normalize_text
from app.services.research.source_extraction import (
    ResearchSourceExtractionResult,
    extract_research_source_records,
)
from app.services.research.source_search import ResearchSourceDocument


logger = logging.getLogger(__name__)

CROSSREF_WORKS_URL = "https://api.crossref.org/works"
RESEARCH_SCHOLAR_SEARCH_CONTRACT_VERSION = "research-scholar-search-v1"


class ResearchScholarSearchProviderResult(BaseModel):
    provider_name: str
    provider_query: str
    status: str
    documents: list[ResearchSourceDocument] = Field(default_factory=list)
    error: str | None = None
    duration_ms: int = 0
    metadata: dict[str, Any] = Field(default_factory=dict)


class ResearchScholarSearchResult(BaseModel):
    result_mode: str = "research_scholar_search"
    contract_version: str = RESEARCH_SCHOLAR_SEARCH_CONTRACT_VERSION
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


async def search_research_scholar_documents(
    *,
    query: str,
    subquestion: str = "",
    limit: int = 5,
    provider_query: str = "",
    provider_source: str = "crossref",
    include_extraction: bool = True,
    metadata: dict[str, Any] | None = None,
) -> ResearchScholarSearchResult:
    """Search scholarly source documents and project them into app fields.

    This adapter may perform an external scholarly-provider call, but it is
    read-only for app state. It does not write research state, evidence,
    long-term memory, recommendation events, provider state, or final facts.
    """

    normalized_query = normalize_text(query)
    normalized_subquestion = normalize_text(subquestion)
    provider_name = normalize_text(provider_source) or "crossref"
    max_results = max(1, min(int(limit or 5), 10))

    if provider_name != "crossref":
        provider_result = ResearchScholarSearchProviderResult(
            provider_name=provider_name,
            provider_query=normalize_text(provider_query) or normalized_query,
            status="failed",
            error=f"unsupported_provider:{provider_name}",
            metadata={"provider_source": provider_name},
        )
    else:
        provider_result = await search_crossref_research_documents(
            query=normalized_query,
            subquestion=normalized_subquestion,
            limit=max_results,
            provider_query=provider_query,
        )

    extraction = extract_research_source_records(
        query=normalized_query,
        subquestion=normalized_subquestion,
        documents=[document.model_dump(mode="json") for document in provider_result.documents],
        provider_source=f"{provider_result.provider_name}_scholar_search",
        metadata={
            **(metadata or {}),
            "scholar_search": {
                "contract_version": RESEARCH_SCHOLAR_SEARCH_CONTRACT_VERSION,
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

    return ResearchScholarSearchResult(
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


async def search_crossref_research_documents(
    *,
    query: str,
    subquestion: str = "",
    limit: int = 5,
    provider_query: str = "",
) -> ResearchScholarSearchProviderResult:
    normalized_query = normalize_text(query)
    search_query = normalize_text(provider_query) or _build_provider_query(
        normalized_query,
        subquestion,
    )
    started_at = time.perf_counter()
    timeout = aiohttp.ClientTimeout(total=12)
    headers = {
        "User-Agent": "AgentHubResearch/1.0 (mailto:research@example.invalid)",
    }

    try:
        async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
            async with session.get(
                CROSSREF_WORKS_URL,
                params={"query": search_query, "rows": max(1, min(limit, 10))},
            ) as response:
                response.raise_for_status()
                payload = await response.json(content_type=None)
    except TimeoutError as exc:
        return _provider_error_result(
            provider_query=search_query,
            status="timeout",
            error=str(exc) or exc.__class__.__name__,
            started_at=started_at,
        )
    except aiohttp.ClientError as exc:
        logger.warning("Crossref research scholar search failed: %s", exc)
        return _provider_error_result(
            provider_query=search_query,
            status="hard_error",
            error=str(exc) or exc.__class__.__name__,
            started_at=started_at,
        )
    except Exception as exc:
        logger.warning("Crossref research scholar search failed: %s", exc)
        return _provider_error_result(
            provider_query=search_query,
            status="hard_error",
            error=str(exc) or exc.__class__.__name__,
            started_at=started_at,
        )

    items = _crossref_items(payload)
    documents = _documents_from_crossref_items(
        items=items,
        query=normalized_query,
        provider_query=search_query,
        limit=limit,
    )
    return ResearchScholarSearchProviderResult(
        provider_name="crossref",
        provider_query=search_query,
        status="ok" if documents else "empty_result",
        documents=documents,
        duration_ms=_duration_ms(started_at),
        metadata={
            "provider_source": "crossref",
            "provider_raw": {
                "result_count": len(items),
                "accepted_document_count": len(documents),
            },
        },
    )


def _documents_from_crossref_items(
    *,
    items: list[dict[str, Any]],
    query: str,
    provider_query: str,
    limit: int,
) -> list[ResearchSourceDocument]:
    documents: list[ResearchSourceDocument] = []
    seen_urls: set[str] = set()
    for index, item in enumerate(items):
        document = _document_from_crossref_item(
            item,
            query=query,
            provider_query=provider_query,
            index=index,
        )
        if document is None:
            continue
        key = (document.source_url or document.source_title).lower()
        if key in seen_urls:
            continue
        seen_urls.add(key)
        documents.append(document)
        if len(documents) >= max(1, min(limit, 10)):
            break
    return documents


def _document_from_crossref_item(
    item: dict[str, Any],
    *,
    query: str,
    provider_query: str,
    index: int,
) -> ResearchSourceDocument | None:
    title = _first_text(item.get("title"))
    abstract = _strip_markup(item.get("abstract"))
    doi = normalize_text(item.get("DOI"))
    source_url = f"https://doi.org/{doi}" if doi else normalize_text(item.get("URL"))
    venue = _first_text(item.get("container-title"))
    year = _published_year(item)
    authors = _authors(item.get("author"))

    if not title and not abstract:
        return None

    content = _paper_content(
        title=title,
        abstract=abstract,
        venue=venue,
        year=year,
        authors=authors,
        doi=doi,
    )
    return ResearchSourceDocument(
        source_type="paper",
        source_title=title or source_url or "Untitled scholarly source",
        source_url=source_url,
        content=content,
        quality=_quality_for_crossref_item(doi=doi, abstract=abstract, venue=venue),
        relevance=_relevance_for_scholar_result(query, title, abstract, venue),
        metadata={
            "provider_source": "crossref",
            "provider_raw": {
                "doi": doi,
                "url": source_url,
                "title": title,
                "abstract": abstract,
                "venue": venue,
                "year": year,
                "authors": authors,
                "type": normalize_text(item.get("type")),
                "score": item.get("score"),
                "query": query,
                "provider_query": provider_query,
                "index": index,
            },
        },
    )


def _paper_content(
    *,
    title: str,
    abstract: str,
    venue: str,
    year: str,
    authors: list[str],
    doi: str,
) -> str:
    parts: list[str] = []
    if title:
        parts.append(title)
    if abstract:
        parts.append(abstract)
    details: list[str] = []
    if venue:
        details.append(f"Published in {venue}")
    if year:
        details.append(f"Year {year}")
    if authors:
        details.append(f"Authors: {', '.join(authors[:5])}")
    if doi:
        details.append(f"DOI {doi}")
    if details:
        parts.append(". ".join(details))
    return _compact_text(". ".join(parts))


def _quality_for_crossref_item(*, doi: str, abstract: str, venue: str) -> str:
    if doi and abstract and venue:
        return "medium"
    if doi and (abstract or venue):
        return "medium"
    return "unknown"


def _relevance_for_scholar_result(
    query: str,
    title: str,
    abstract: str,
    venue: str,
) -> int:
    terms = set(_terms(query))
    if not terms:
        return 3
    haystack = f"{title} {abstract} {venue}".lower()
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


def _crossref_items(payload: Any) -> list[dict[str, Any]]:
    if not isinstance(payload, dict):
        return []
    message = payload.get("message")
    if not isinstance(message, dict):
        return []
    items = message.get("items")
    if not isinstance(items, list):
        return []
    return [item for item in items if isinstance(item, dict)]


def _first_text(value: Any) -> str:
    if isinstance(value, list):
        for item in value:
            text = normalize_text(item)
            if text:
                return text
        return ""
    return normalize_text(value)


def _strip_markup(value: Any) -> str:
    text = normalize_text(value)
    if not text:
        return ""
    text = re.sub(r"<[^>]+>", " ", text)
    return _compact_text(text)


def _authors(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    authors: list[str] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        name = normalize_text(item.get("name"))
        if not name:
            given = normalize_text(item.get("given"))
            family = normalize_text(item.get("family"))
            name = _compact_text(f"{given} {family}")
        if name:
            authors.append(name)
    return authors


def _published_year(item: dict[str, Any]) -> str:
    for field in ("published-print", "published-online", "published", "issued"):
        value = item.get(field)
        if not isinstance(value, dict):
            continue
        date_parts = value.get("date-parts")
        if (
            isinstance(date_parts, list)
            and date_parts
            and isinstance(date_parts[0], list)
            and date_parts[0]
        ):
            return normalize_text(date_parts[0][0])
    return ""


def _build_provider_query(query: str, subquestion: str) -> str:
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


def _provider_error_result(
    *,
    provider_query: str,
    status: str,
    error: str,
    started_at: float,
) -> ResearchScholarSearchProviderResult:
    return ResearchScholarSearchProviderResult(
        provider_name="crossref",
        provider_query=provider_query,
        status=status,
        error=error,
        duration_ms=_duration_ms(started_at),
        metadata={
            "provider_source": "crossref",
            "provider_raw": {
                "status": status,
                "error": error,
            },
        },
    )


def _compact_text(text: str) -> str:
    return " ".join(unescape(str(text or "")).split()).strip()


def _duration_ms(started_at: float) -> int:
    return max(0, int((time.perf_counter() - started_at) * 1000))
