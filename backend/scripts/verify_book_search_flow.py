"""Verify ordinary book-search status and loop guard without network access."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from uuid import uuid4

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.agents.tools import books as book_tools
from app.services.book_search import BookSearchCacheResult
from app.services.book_search_contracts import get_book_search_hint
from app.utils.logging import request_id_scope


class _FakeSessionContext:
    async def __aenter__(self):
        return object()

    async def __aexit__(self, exc_type, exc, tb):
        return None


class _FakeDatabase:
    def session(self) -> _FakeSessionContext:
        return _FakeSessionContext()


class _FakeBook:
    def __init__(self, title: str) -> None:
        self.id = uuid4()
        self.title = title
        self.authors = ["Example Author"]
        self.summary = "A warm, character-driven example novel."
        self.rating = None
        self.source_name = "test"
        self.source_url = "https://example.test/book"
        self.external_id = "example-book"


async def _fake_ok_search(session, *, query: str, limit: int) -> BookSearchCacheResult:
    return BookSearchCacheResult(
        query=query,
        status="ok",
        books=[_FakeBook("Example Novel")],
        source="test",
        next_action_hint=get_book_search_hint("ok"),
        duration_ms=3,
    )


async def _fake_empty_search(session, *, query: str, limit: int) -> BookSearchCacheResult:
    return BookSearchCacheResult(
        query=query,
        status="empty_result",
        books=[],
        source="test",
        next_action_hint=get_book_search_hint("empty_result"),
        duration_ms=3,
    )


async def main() -> None:
    original_get_database = book_tools.get_database
    original_search = book_tools.search_and_cache_books_with_status
    book_tools.reset_search_books_guard()

    try:
        book_tools.get_database = lambda: _FakeDatabase()
        book_tools.search_and_cache_books_with_status = _fake_ok_search

        with request_id_scope("verify-ordinary-search-once"):
            first = json.loads(
                await book_tools._search_books_impl("warm novels", limit=3)
            )
            second = json.loads(
                await book_tools._search_books_impl("another query", limit=3)
            )

        assert first["status"] == "ok", first
        assert first["result_count"] == 1, first
        assert second["status"] == "loop_detected", second
        assert second["books"] == [], second

        book_tools.reset_search_books_guard()
        with request_id_scope("verify-explicit-second-search"):
            first = json.loads(await book_tools._search_books_impl("warm novels"))
            second = json.loads(
                await book_tools._search_books_impl(
                    "refined warm novels",
                    allow_additional_search=True,
                )
            )

        assert first["status"] == "ok", first
        assert second["status"] == "ok", second

        book_tools.reset_search_books_guard()
        book_tools.search_and_cache_books_with_status = _fake_empty_search
        with request_id_scope("verify-empty-search-status"):
            empty = json.loads(await book_tools._search_books_impl("no results"))

        assert empty["status"] == "empty_result", empty
        assert empty["result_count"] == 0, empty
        assert "Do not repeat" in empty["next_action_hint"], empty

    finally:
        book_tools.get_database = original_get_database
        book_tools.search_and_cache_books_with_status = original_search
        book_tools.reset_search_books_guard()

    print("book search verification passed")


if __name__ == "__main__":
    asyncio.run(main())
