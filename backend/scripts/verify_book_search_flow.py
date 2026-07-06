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
from app.services.book_intent import (
    build_book_turn_policy_prompt,
    build_turn_policy,
    has_explicit_book_search_intent,
)
from app.services.book_search import BookSearchCacheResult
from app.services.book_search_contracts import get_book_search_hint
from app.utils.logging import request_id_scope
from app.utils.turn_context import user_message_scope


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
    search_call_count = 0

    try:
        style_question = "我喜欢非暴力沟通这种书，这种书的风格是什么样的？"
        explicit_recommendation = "请推荐几本非暴力沟通类似的书"
        style_policy = build_turn_policy(style_question)
        recommendation_policy = build_turn_policy(explicit_recommendation)

        assert not has_explicit_book_search_intent(style_question)
        assert has_explicit_book_search_intent(explicit_recommendation)
        assert style_policy.intent.primary_intent == "update_memory", style_policy
        assert "update_memory" in style_policy.intent.intents, style_policy
        assert style_policy.can_write_memory is True, style_policy
        assert style_policy.can_search_books is False, style_policy
        assert style_policy.can_recommend_books is False, style_policy
        assert recommendation_policy.intent.primary_intent == "recommend_books", (
            recommendation_policy
        )
        assert recommendation_policy.can_search_books is True, recommendation_policy
        assert recommendation_policy.max_book_search_calls == 1, recommendation_policy
        assert "contract_version: turn-policy-v1" in build_book_turn_policy_prompt(
            style_question
        )
        assert "can_search_books: no" in build_book_turn_policy_prompt(style_question)
        assert "can_search_books: yes" in build_book_turn_policy_prompt(
            explicit_recommendation
        )

        book_tools.get_database = lambda: _FakeDatabase()

        async def fake_ok_search_with_count(session, *, query: str, limit: int):
            nonlocal search_call_count
            search_call_count += 1
            return await _fake_ok_search(session, query=query, limit=limit)

        book_tools.search_and_cache_books_with_status = fake_ok_search_with_count

        book_tools.reset_search_books_guard()
        with request_id_scope("verify-style-question-blocks-search"):
            with user_message_scope(style_question):
                blocked = json.loads(
                    await book_tools._search_books_impl(
                        "非暴力沟通 同类书籍 沟通技巧 共情",
                        limit=5,
                    )
                )

        assert blocked["status"] == "intent_blocked", blocked
        assert blocked["result_count"] == 0, blocked
        assert search_call_count == 0, search_call_count

        book_tools.reset_search_books_guard()
        with request_id_scope("verify-explicit-recommendation-search"):
            with user_message_scope(explicit_recommendation):
                explicit = json.loads(
                    await book_tools._search_books_impl(
                        "非暴力沟通 同类书籍 沟通技巧 共情",
                        limit=3,
                    )
                )

        assert explicit["status"] == "ok", explicit
        assert explicit["result_count"] == 1, explicit
        assert search_call_count == 1, search_call_count

        with request_id_scope("verify-ordinary-search-once"):
            with user_message_scope("请推荐一些 warm novels"):
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
            with user_message_scope("请推荐一些 warm novels，再补一个 refined search"):
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
            with user_message_scope("请推荐 no results 相关的书"):
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
