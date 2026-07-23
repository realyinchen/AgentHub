from __future__ import annotations

import ipaddress
import logging
import time
from html import unescape
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urlparse

import aiohttp
from pydantic import BaseModel, Field

from app.services.research.contracts import normalize_text
from app.services.research.source_extraction import (
    ResearchSourceExtractionResult,
    extract_research_source_records,
)
from app.services.research.source_search import ResearchSourceDocument


logger = logging.getLogger(__name__)

RESEARCH_SOURCE_VISIT_CONTRACT_VERSION = "research-source-visit-v1"
MAX_FETCH_BYTES = 512_000
MAX_DOCUMENT_CHARS = 24_000
BLOCKED_HOSTS = frozenset({"localhost", "127.0.0.1", "::1", "0.0.0.0"})


class ResearchSourceVisitResult(BaseModel):
    result_mode: str = "research_source_visit"
    contract_version: str = RESEARCH_SOURCE_VISIT_CONTRACT_VERSION
    status: str
    url: str
    final_url: str = ""
    query: str = ""
    subquestion: str = ""
    source_document: ResearchSourceDocument | None = None
    extraction: ResearchSourceExtractionResult
    extracted_count: int = 0
    error: str | None = None
    duration_ms: int = 0
    metadata: dict[str, Any] = Field(default_factory=dict)


class _HtmlDocumentParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.title_parts: list[str] = []
        self.text_parts: list[str] = []
        self._in_title = False
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style", "noscript", "svg"}:
            self._skip_depth += 1
            return
        if tag == "title":
            self._in_title = True

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript", "svg"} and self._skip_depth:
            self._skip_depth -= 1
            return
        if tag == "title":
            self._in_title = False

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        text = _compact_text(data)
        if not text:
            return
        if self._in_title:
            self.title_parts.append(text)
        else:
            self.text_parts.append(text)

    @property
    def title(self) -> str:
        return _compact_text(" ".join(self.title_parts))

    @property
    def text(self) -> str:
        return _compact_text(" ".join(self.text_parts))


async def fetch_research_source_document(
    *,
    url: str,
    query: str = "",
    subquestion: str = "",
    provider_source: str = "source_visit",
    include_extraction: bool = True,
    timeout_seconds: int = 12,
    metadata: dict[str, Any] | None = None,
) -> ResearchSourceVisitResult:
    """Fetch one approved URL into a source document for research extraction.

    This adapter may perform an external URL fetch. It is read-only for app
    state: no research state, evidence, long-term memory, recommendation event,
    provider state, or final-answer fact is written here.
    """

    normalized_url = normalize_text(url)
    normalized_query = normalize_text(query)
    normalized_subquestion = normalize_text(subquestion)
    provider_name = normalize_text(provider_source) or "source_visit"
    started_at = time.perf_counter()
    url_error = _url_error(normalized_url)
    if url_error:
        return _result_from_document(
            url=normalized_url,
            final_url="",
            query=normalized_query,
            subquestion=normalized_subquestion,
            provider_source=provider_name,
            status=url_error,
            source_document=None,
            include_extraction=include_extraction,
            error=url_error,
            duration_ms=_duration_ms(started_at),
            metadata=metadata,
        )

    fetch = await _fetch_url(
        normalized_url,
        timeout_seconds=max(1, min(int(timeout_seconds or 12), 30)),
    )
    if fetch["status"] != "ok":
        return _result_from_document(
            url=normalized_url,
            final_url=fetch.get("final_url", ""),
            query=normalized_query,
            subquestion=normalized_subquestion,
            provider_source=provider_name,
            status=fetch["status"],
            source_document=None,
            include_extraction=include_extraction,
            error=fetch.get("error"),
            duration_ms=_duration_ms(started_at),
            metadata={**(metadata or {}), "fetch": fetch},
        )

    title, content = _extract_document_text(fetch["body"], fetch["content_type"])
    if not content:
        return _result_from_document(
            url=normalized_url,
            final_url=fetch.get("final_url", normalized_url),
            query=normalized_query,
            subquestion=normalized_subquestion,
            provider_source=provider_name,
            status="empty_result",
            source_document=None,
            include_extraction=include_extraction,
            error="empty_document_text",
            duration_ms=_duration_ms(started_at),
            metadata={**(metadata or {}), "fetch": fetch},
        )

    document = ResearchSourceDocument(
        source_type="web",
        source_title=title or fetch.get("final_url") or normalized_url,
        source_url=fetch.get("final_url") or normalized_url,
        content=content[:MAX_DOCUMENT_CHARS],
        quality="unknown",
        relevance=_relevance_for_document(normalized_query, normalized_subquestion, content),
        metadata={
            **(metadata or {}),
            "provider_source": provider_name,
            "provider_raw": {
                "requested_url": normalized_url,
                "final_url": fetch.get("final_url"),
                "content_type": fetch.get("content_type"),
                "status_code": fetch.get("status_code"),
                "byte_count": fetch.get("byte_count"),
                "truncated": fetch.get("truncated"),
            },
            "source_visit": {
                "contract_version": RESEARCH_SOURCE_VISIT_CONTRACT_VERSION,
            },
        },
    )
    return _result_from_document(
        url=normalized_url,
        final_url=document.source_url,
        query=normalized_query,
        subquestion=normalized_subquestion,
        provider_source=provider_name,
        status="ok",
        source_document=document,
        include_extraction=include_extraction,
        error=None,
        duration_ms=_duration_ms(started_at),
        metadata={**(metadata or {}), "fetch": fetch},
    )


async def _fetch_url(url: str, *, timeout_seconds: int) -> dict[str, Any]:
    timeout = aiohttp.ClientTimeout(total=timeout_seconds)
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125 Safari/537.36"
        )
    }
    try:
        async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
            async with session.get(url, allow_redirects=True) as response:
                body = await response.content.read(MAX_FETCH_BYTES + 1)
                truncated = len(body) > MAX_FETCH_BYTES
                if truncated:
                    body = body[:MAX_FETCH_BYTES]
                text = body.decode(response.charset or "utf-8", errors="replace")
                if response.status >= 400:
                    return {
                        "status": "hard_error",
                        "error": f"http_status:{response.status}",
                        "status_code": response.status,
                        "final_url": str(response.url),
                        "content_type": response.headers.get("content-type", ""),
                        "byte_count": len(body),
                        "truncated": truncated,
                    }
                return {
                    "status": "ok",
                    "body": text,
                    "status_code": response.status,
                    "final_url": str(response.url),
                    "content_type": response.headers.get("content-type", ""),
                    "byte_count": len(body),
                    "truncated": truncated,
                }
    except TimeoutError as exc:
        return {"status": "timeout", "error": str(exc) or exc.__class__.__name__}
    except aiohttp.ClientError as exc:
        logger.warning("Research source visit failed: %s", exc)
        return {"status": "hard_error", "error": str(exc) or exc.__class__.__name__}
    except Exception as exc:
        logger.warning("Research source visit failed: %s", exc)
        return {"status": "hard_error", "error": str(exc) or exc.__class__.__name__}


def _result_from_document(
    *,
    url: str,
    final_url: str,
    query: str,
    subquestion: str,
    provider_source: str,
    status: str,
    source_document: ResearchSourceDocument | None,
    include_extraction: bool,
    error: str | None,
    duration_ms: int,
    metadata: dict[str, Any] | None,
) -> ResearchSourceVisitResult:
    extraction = extract_research_source_records(
        query=query,
        subquestion=subquestion,
        documents=[source_document.model_dump(mode="json")] if source_document else [],
        provider_source=provider_source,
        metadata={
            **(metadata or {}),
            "source_visit": {
                "contract_version": RESEARCH_SOURCE_VISIT_CONTRACT_VERSION,
                "url": url,
                "final_url": final_url,
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
    final_status = _result_status(status, bool(source_document), extraction.extracted_count)
    return ResearchSourceVisitResult(
        status=final_status,
        url=url,
        final_url=final_url,
        query=query,
        subquestion=subquestion,
        source_document=source_document,
        extraction=extraction,
        extracted_count=extraction.extracted_count,
        error=error,
        duration_ms=duration_ms,
        metadata={
            **(metadata or {}),
            "writes_research_state": False,
            "writes_evidence": False,
            "writes_long_term_memory": False,
            "writes_recommendation_events": False,
            "external_call": status not in {"invalid_url", "blocked_url"},
            "provider_source": provider_source,
            "fetch_status": status,
        },
    )


def _result_status(status: str, has_document: bool, extracted_count: int) -> str:
    if status != "ok":
        return status
    if not has_document:
        return "empty_result"
    if extracted_count > 0:
        return "ok"
    return "no_extractable_claims"


def _extract_document_text(body: str, content_type: str) -> tuple[str, str]:
    if "html" not in content_type.lower():
        text = _compact_text(body)
        return "", text
    parser = _HtmlDocumentParser()
    parser.feed(body)
    return parser.title, parser.text


def _url_error(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        return "invalid_url"
    if not parsed.hostname:
        return "invalid_url"
    host = parsed.hostname.lower()
    if host in BLOCKED_HOSTS or host.endswith(".local"):
        return "blocked_url"
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return ""
    if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast:
        return "blocked_url"
    return ""


def _relevance_for_document(query: str, subquestion: str, content: str) -> int:
    terms = {
        term
        for term in f"{query} {subquestion}".lower().replace("/", " ").split()
        if len(term) >= 3
    }
    if not terms:
        return 3
    haystack = content.lower()
    matches = sum(1 for term in terms if term in haystack)
    if matches <= 0:
        return 2
    if matches >= 3:
        return 5
    return 3 + min(matches, 2)


def _compact_text(text: str) -> str:
    return " ".join(unescape(str(text or "")).split()).strip()


def _duration_ms(started_at: float) -> int:
    return max(0, int((time.perf_counter() - started_at) * 1000))
