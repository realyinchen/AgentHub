"""Book candidate cache fusion backed by the external-search gateway."""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from html import unescape
from urllib.parse import urlparse

from sqlalchemy import String, cast, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.crud.book import upsert_book
from app.models.book import Book
from app.services.book_search_contracts import (
    BookCandidateSearchResult,
    BookSearchStatus,
    get_book_search_hint,
)
from app.services.external_search import SearchRequest, get_search_gateway

BOOK_CACHE_CONTRACT_VERSION = "book-cache-fusion-v1"
_QUERY_STOPWORDS = {
    "a",
    "an",
    "and",
    "book",
    "books",
    "for",
    "i",
    "me",
    "novel",
    "novels",
    "of",
    "or",
    "please",
    "recommend",
    "some",
    "the",
    "to",
}


@dataclass(frozen=True)
class BookSearchCacheResult:
    """Result of one ordinary book search after local cache upsert."""

    query: str
    status: BookSearchStatus
    books: list[Book]
    source: str = "external_search"
    next_action_hint: str = ""
    error: str | None = None
    duration_ms: int = 0
    metadata: dict = field(default_factory=dict)
    candidate_sources: dict[str, dict] = field(default_factory=dict)

    @property
    def result_count(self) -> int:
        return len(self.books)


def _compact_text(text: str) -> str:
    return re.sub(r"\s+", " ", unescape(text)).strip()


def _infer_source_name(url: str) -> str:
    host = urlparse(url).netloc.lower()
    if "douban.com" in host:
        return "douban"
    return host or "web"


def _extract_external_id(url: str) -> str | None:
    match = re.search(r"/subject/(\d+)", url)
    return match.group(1) if match else None


def _normalize_book_title(raw_title: str) -> str:
    title = raw_title
    title = re.sub(r"\s*[\(_-]?豆瓣读书.*$", "", title, flags=re.IGNORECASE)
    title = re.sub(r"\s*[\(_-]?豆瓣.*$", "", title, flags=re.IGNORECASE)
    title = re.sub(r"\s*-\s*book\.douban\.com.*$", "", title, flags=re.IGNORECASE)
    return _compact_text(title).strip(" -_")


def _candidate_to_book_data(candidate: dict[str, str]) -> dict:
    url = candidate.get("url", "")
    raw_title = candidate.get("title", "")
    snippet = candidate.get("snippet", "")
    return {
        "title": _normalize_book_title(raw_title) or raw_title,
        "authors": [],
        "tags": [],
        "summary": snippet or None,
        "source_name": _infer_source_name(url),
        "source_url": url,
        "external_id": _extract_external_id(url),
        "raw_data": {
            "search_title": raw_title,
            "search_snippet": snippet,
            "search_url": url,
        },
    }


async def search_external_book_candidates(
    query: str,
    limit: int = 5,
) -> BookCandidateSearchResult:
    """Search public book pages and return structured ordinary search state."""
    started_at = time.perf_counter()
    result = await get_search_gateway().search(
        SearchRequest(
            query=query,
            max_results=max(1, min(limit, 10)),
            detail="standard",
            include_domains=["book.douban.com"],
            language="zh",
            zone="cn",
        )
    )
    books = [
        _candidate_to_book_data(
            {
                "title": hit.title,
                "url": hit.url,
                "snippet": hit.snippet or hit.content,
            }
        )
        for hit in result.hits[:limit]
    ]
    duration_ms = int((time.perf_counter() - started_at) * 1000)
    if books:
        status: BookSearchStatus = "ok"
    elif result.outcome == "empty":
        status = "empty_result"
    elif any(item.error_type == "timeout" for item in result.attempts):
        status = "timeout"
    else:
        status = "hard_error"
    return BookCandidateSearchResult(
        query=query,
        provider_query=result.effective_query or query,
        status=status,
        candidates=books,
        source=result.provider or "external_search",
        next_action_hint=get_book_search_hint(status),
        error=result.error or None,
        duration_ms=duration_ms,
    )


async def search_duckduckgo_book_candidates(
    query: str,
    limit: int = 5,
) -> BookCandidateSearchResult:
    """Compatibility alias; all network access now goes through SearchGateway."""

    return await search_external_book_candidates(query=query, limit=limit)


async def search_duckduckgo_books(query: str, limit: int = 5) -> list[dict]:
    """Compatibility alias for legacy callers."""
    result = await search_external_book_candidates(query=query, limit=limit)
    return result.candidates


async def search_and_cache_books_with_status(
    db: AsyncSession,
    query: str,
    limit: int = 5,
) -> BookSearchCacheResult:
    started_at = time.perf_counter()
    requested_limit = max(1, limit)
    cached_books = await search_cached_books(db, query=query, limit=requested_limit)
    external_result: BookCandidateSearchResult | None = None
    external_books: list[Book] = []
    external_limit = max(0, requested_limit - len(cached_books))

    if external_limit > 0:
        external_result = await search_external_book_candidates(
            query=query,
            limit=external_limit,
        )
        for candidate in external_result.candidates:
            external_books.append(await upsert_book(db, candidate))

    books = _merge_book_candidates([*cached_books, *external_books], requested_limit)
    duration_ms = int((time.perf_counter() - started_at) * 1000)
    status = _fused_status(books, external_result)
    candidate_sources = _candidate_sources(
        query=query,
        cached_books=cached_books,
        external_books=external_books,
        external_result=external_result,
        final_books=books,
    )
    return BookSearchCacheResult(
        query=query,
        status=status,
        books=books,
        source=_fused_source(
            cache_hit_count=len(cached_books),
            external_result=external_result,
        ),
        next_action_hint=get_book_search_hint(status),
        error=external_result.error if external_result is not None else None,
        duration_ms=duration_ms,
        metadata={
            "contract_version": BOOK_CACHE_CONTRACT_VERSION,
            "cache_hit_count": len(cached_books),
            "external_search_performed": external_result is not None,
            "external_status": external_result.status if external_result else None,
            "external_result_count": (
                external_result.result_count if external_result else 0
            ),
            "merged_result_count": len(books),
            "requested_limit": requested_limit,
        },
        candidate_sources=candidate_sources,
    )


async def search_cached_books(
    db: AsyncSession,
    *,
    query: str,
    limit: int = 5,
) -> list[Book]:
    terms = _query_terms(query, max_terms=8)
    if not terms:
        return []

    predicates = []
    for term in terms:
        pattern = f"%{term}%"
        predicates.extend(
            [
                Book.title.ilike(pattern),
                Book.summary.ilike(pattern),
                cast(Book.authors, String).ilike(pattern),
                cast(Book.tags, String).ilike(pattern),
                cast(Book.raw_data, String).ilike(pattern),
            ]
        )

    result = await db.execute(
        select(Book)
        .where(or_(*predicates))
        .order_by(Book.last_seen_at.desc(), Book.updated_at.desc())
        .limit(max(1, min(limit * 5, 50)))
    )
    scored = [
        (_cache_match_score(book, terms), book)
        for book in result.scalars().all()
    ]
    scored = [(score, book) for score, book in scored if score > 0]
    scored.sort(key=lambda item: (item[0], item[1].last_seen_at), reverse=True)
    return [book for _, book in scored[: max(1, limit)]]


def _merge_book_candidates(books: list[Book], limit: int) -> list[Book]:
    seen: set[str] = set()
    merged: list[Book] = []
    for book in books:
        key = _book_identity(book)
        if not key or key in seen:
            continue
        seen.add(key)
        merged.append(book)
        if len(merged) >= limit:
            break
    return merged


def _candidate_sources(
    *,
    query: str,
    cached_books: list[Book],
    external_books: list[Book],
    external_result: BookCandidateSearchResult | None,
    final_books: list[Book],
) -> dict[str, dict]:
    terms = _query_terms(query, max_terms=8)
    source_by_id: dict[str, dict] = {}
    for index, book in enumerate(cached_books):
        source_by_id[str(book.id)] = {
            "source": "book_cache",
            "candidate_source": "book_cache",
            "rank_index": index,
            "match_score": round(_cache_match_score(book, terms), 4),
            "reason": "candidate matched local Book Cache before external search",
        }
    external_source = external_result.source if external_result is not None else "external"
    for index, book in enumerate(external_books):
        source_by_id.setdefault(
            str(book.id),
            {
                "source": external_source,
                "candidate_source": "external_search",
                "rank_index": index,
                "provider_query": (
                    external_result.provider_query if external_result is not None else ""
                ),
                "provider_status": (
                    external_result.status if external_result is not None else ""
                ),
                "reason": "candidate was added from external book search",
            },
        )
    return {
        str(book.id): {
            **source_by_id.get(
                str(book.id),
                {
                    "source": getattr(book, "source_name", "") or "unknown",
                    "candidate_source": "unknown",
                    "reason": "candidate source metadata was unavailable",
                },
            ),
            "book_id": str(book.id),
            "title": getattr(book, "title", ""),
        }
        for book in final_books
    }


def _book_identity(book: Book) -> str:
    source_url = str(getattr(book, "source_url", "") or "").strip().lower()
    if source_url:
        return f"url:{source_url}"
    external_id = str(getattr(book, "external_id", "") or "").strip().lower()
    source_name = str(getattr(book, "source_name", "") or "").strip().lower()
    if external_id:
        return f"external:{source_name}:{external_id}"
    return f"title:{str(getattr(book, 'title', '') or '').strip().lower()}"


def _fused_status(
    books: list[Book],
    external_result: BookCandidateSearchResult | None,
) -> BookSearchStatus:
    if books:
        return "ok"
    if external_result is not None:
        return external_result.status
    return "empty_result"


def _fused_source(
    *,
    cache_hit_count: int,
    external_result: BookCandidateSearchResult | None,
) -> str:
    if cache_hit_count and external_result is not None:
        return f"book_cache+{external_result.source}"
    if cache_hit_count:
        return "book_cache"
    if external_result is not None:
        return external_result.source
    return "book_cache"


def _cache_match_score(book: Book, terms: list[str]) -> float:
    haystack = " ".join(
        str(part or "")
        for part in [
            getattr(book, "title", ""),
            getattr(book, "subtitle", ""),
            " ".join(getattr(book, "authors", None) or []),
            " ".join(getattr(book, "tags", None) or []),
            getattr(book, "summary", ""),
            str(getattr(book, "raw_data", None) or ""),
        ]
    ).lower()
    score = 0.0
    title = str(getattr(book, "title", "") or "").lower()
    tags = " ".join(getattr(book, "tags", None) or []).lower()
    for term in terms:
        if term in haystack:
            score += 1.0
        if term in title:
            score += 0.6
        if term in tags:
            score += 0.4
    return score


def _query_terms(query: str, max_terms: int = 12) -> list[str]:
    terms: list[str] = []
    seen: set[str] = set()
    for match in re.findall(r"[\w\u4e00-\u9fff]+", query.lower()):
        if len(match) < 2 or match in _QUERY_STOPWORDS or match in seen:
            continue
        seen.add(match)
        terms.append(match)
        if len(terms) >= max_terms:
            break
    return terms


async def search_and_cache_books(
    db: AsyncSession,
    query: str,
    limit: int = 5,
) -> list[Book]:
    result = await search_and_cache_books_with_status(db=db, query=query, limit=limit)
    return result.books
