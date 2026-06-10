"""Book search service backed by DuckDuckGo HTML results.

This service intentionally avoids relying on an unofficial Douban API. It uses
DuckDuckGo to discover public book pages, then caches lightweight metadata in
the local database for recommendation and memory workflows.
"""

from __future__ import annotations

import logging
import re
from html import unescape
from html.parser import HTMLParser
from urllib.parse import parse_qs, unquote, urlparse

import aiohttp
from sqlalchemy.ext.asyncio import AsyncSession

from app.crud.book import upsert_book
from app.models.book import Book

logger = logging.getLogger(__name__)

DUCKDUCKGO_HTML_URL = "https://html.duckduckgo.com/html/"


class _DuckDuckGoResultParser(HTMLParser):
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
        elif self._in_snippet:
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


def _compact_text(text: str) -> str:
    return re.sub(r"\s+", " ", unescape(text)).strip()


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


def _build_duckduckgo_query(query: str) -> str:
    cleaned = query.strip()
    if "site:" in cleaned:
        return cleaned
    return f"site:book.douban.com/subject {cleaned} 豆瓣 读书 评分 简介"


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


async def search_duckduckgo_books(query: str, limit: int = 5) -> list[dict]:
    """Search public book pages with DuckDuckGo and return normalized data."""
    params = {"q": _build_duckduckgo_query(query)}
    timeout = aiohttp.ClientTimeout(total=12)
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125 Safari/537.36"
        )
    }

    try:
        async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
            async with session.get(DUCKDUCKGO_HTML_URL, params=params) as response:
                response.raise_for_status()
                html = await response.text()
    except Exception as exc:
        logger.warning("DuckDuckGo book search failed: %s", exc)
        return []

    parser = _DuckDuckGoResultParser()
    parser.feed(html)

    seen: set[str] = set()
    books: list[dict] = []
    for candidate in parser.results:
        url = candidate.get("url", "")
        if not url or url in seen:
            continue
        seen.add(url)
        books.append(_candidate_to_book_data(candidate))
        if len(books) >= limit:
            break

    return books


async def search_and_cache_books(
    db: AsyncSession,
    query: str,
    limit: int = 5,
) -> list[Book]:
    candidates = await search_duckduckgo_books(query=query, limit=limit)
    books: list[Book] = []
    for candidate in candidates:
        books.append(await upsert_book(db, candidate))
    return books
