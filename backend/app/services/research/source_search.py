from __future__ import annotations

import logging
import time
from html import unescape
from html.parser import HTMLParser
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

import aiohttp
from pydantic import BaseModel, Field, field_validator

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


logger = logging.getLogger(__name__)

DUCKDUCKGO_HTML_URL = "https://html.duckduckgo.com/html/"
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


class _DuckDuckGoSearchResultParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.results: list[dict[str, str]] = []
        self._in_title = False
        self._in_snippet = False
        self._title_parts: list[str] = []
        self._snippet_parts: list[str] = []
        self._current_url = ""

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_dict = {name: value or "" for name, value in attrs}
        class_name = attrs_dict.get("class", "")
        if tag == "a" and "result__a" in class_name:
            self._in_title = True
            self._title_parts = []
            self._current_url = _unwrap_duckduckgo_url(attrs_dict.get("href", ""))
            return
        if "result__snippet" in class_name:
            self._in_snippet = True
            self._snippet_parts = []

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self._title_parts.append(data)
            return
        if self._in_snippet:
            self._snippet_parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if self._in_title and tag == "a":
            title = _compact_text("".join(self._title_parts))
            if title and self._current_url:
                self.results.append(
                    {
                        "title": title,
                        "url": self._current_url,
                        "snippet": "",
                    }
                )
            self._in_title = False
            return

        if self._in_snippet and tag in {"a", "div"}:
            snippet = _compact_text("".join(self._snippet_parts))
            if snippet and self.results:
                self.results[-1]["snippet"] = snippet
            self._in_snippet = False


async def search_research_source_documents(
    *,
    query: str,
    subquestion: str = "",
    limit: int = 5,
    provider_query: str = "",
    provider_source: str = "duckduckgo",
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
    provider_name = normalize_text(provider_source) or "duckduckgo"
    max_results = max(1, min(int(limit or 5), 10))

    if provider_name != "duckduckgo":
        provider_result = ResearchSourceSearchProviderResult(
            provider_name=provider_name,
            provider_query=normalize_text(provider_query) or normalized_query,
            status="failed",
            error=f"unsupported_provider:{provider_name}",
            metadata={"provider_source": provider_name},
        )
    else:
        provider_result = await search_duckduckgo_research_documents(
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


async def search_duckduckgo_research_documents(
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
    timeout = aiohttp.ClientTimeout(total=12)
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125 Safari/537.36"
        )
    }

    try:
        async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
            async with session.get(
                DUCKDUCKGO_HTML_URL,
                params={"q": search_query},
            ) as response:
                response.raise_for_status()
                html = await response.text()
    except TimeoutError as exc:
        return _provider_error_result(
            provider_query=search_query,
            status="timeout",
            error=str(exc) or exc.__class__.__name__,
            started_at=started_at,
        )
    except aiohttp.ClientError as exc:
        logger.warning("DuckDuckGo research source search failed: %s", exc)
        return _provider_error_result(
            provider_query=search_query,
            status="hard_error",
            error=str(exc) or exc.__class__.__name__,
            started_at=started_at,
        )
    except Exception as exc:
        logger.warning("DuckDuckGo research source search failed: %s", exc)
        return _provider_error_result(
            provider_query=search_query,
            status="hard_error",
            error=str(exc) or exc.__class__.__name__,
            started_at=started_at,
        )

    parser = _DuckDuckGoSearchResultParser()
    parser.feed(html)
    documents = _documents_from_search_results(
        results=parser.results,
        query=normalized_query,
        provider_query=search_query,
        limit=limit,
    )
    status = "ok" if documents else _empty_status(html)
    return ResearchSourceSearchProviderResult(
        provider_name="duckduckgo",
        provider_query=search_query,
        status=status,
        documents=documents,
        duration_ms=_duration_ms(started_at),
        metadata={
            "provider_source": "duckduckgo",
            "provider_raw": {
                "result_count": len(parser.results),
                "accepted_document_count": len(documents),
            },
        },
    )


def _documents_from_search_results(
    *,
    results: list[dict[str, str]],
    query: str,
    provider_query: str,
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
                    "provider_source": "duckduckgo",
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


def _empty_status(html: str) -> str:
    if not normalize_text(html):
        return "hard_error"
    if "result__a" not in html and "result__snippet" not in html:
        return "hard_error"
    return "empty_result"


def _provider_error_result(
    *,
    provider_query: str,
    status: str,
    error: str,
    started_at: float,
) -> ResearchSourceSearchProviderResult:
    return ResearchSourceSearchProviderResult(
        provider_name="duckduckgo",
        provider_query=provider_query,
        status=status,
        error=error,
        duration_ms=_duration_ms(started_at),
        metadata={
            "provider_source": "duckduckgo",
            "provider_raw": {
                "status": status,
                "error": error,
            },
        },
    )


def _compact_text(text: str) -> str:
    return " ".join(unescape(str(text or "")).split()).strip()


def _unwrap_duckduckgo_url(url: str) -> str:
    if not url:
        return ""
    if url.startswith("//"):
        url = f"https:{url}"
    parsed = urlparse(url)
    if "duckduckgo.com" in parsed.netloc:
        target = parse_qs(parsed.query).get("uddg")
        if target:
            return unquote(target[0])
    return url


def _source_type(value: Any) -> str:
    token = normalize_research_token(value or "web")
    return token if token in EVIDENCE_SOURCE_TYPES else "other"


def _quality(value: Any) -> str:
    token = normalize_research_token(value or "unknown")
    return token if token in EVIDENCE_QUALITIES else "unknown"


def _duration_ms(started_at: float) -> int:
    return max(0, int((time.perf_counter() - started_at) * 1000))
