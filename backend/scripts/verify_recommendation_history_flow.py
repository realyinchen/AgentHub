"""Verify Phase P4 recommendation-history and suppression explanation flow.

This check uses local PostgreSQL and no external network. It verifies:
- explicit read/history/suppression questions get a dedicated turn policy
- ordinary recommendations still suppress read or rejected books
- suppressed records are available through explicit history/explanation mode
- history access is read-only and does not make suppressed books candidates
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import uuid
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import text

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.agents.tools import books as book_tools
from app.crud.book import create_book_interaction, create_recommendation_event
from app.infra.database import dispose_database, get_database, init_database
from app.infra.llm.embedding import init_embedding_model
from app.schemas.book import BookInteractionCreate
from app.services.book_intent import build_turn_policy
from app.services.book_search import BookSearchCacheResult
from app.services.book_search_contracts import get_book_search_hint
from app.services.recommendation_signals import RecommendationSignalCreate
from app.utils.logging import request_id_scope
from app.utils.turn_context import user_message_scope
from scripts.init_database import _init_postgres


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


class _FakeBook:
    def __init__(self, title: str) -> None:
        self.id = uuid.uuid4()
        self.title = title
        self.subtitle = None
        self.authors = ["Example Author"]
        self.tags = ["warm"]
        self.summary = f"{title} summary."
        self.rating = None
        self.source_name = "test"
        self.source_url = f"https://example.test/{self.id}"
        self.external_id = str(self.id)
        self.raw_data = {}


async def _fake_search(session, *, query: str, limit: int) -> BookSearchCacheResult:
    return BookSearchCacheResult(
        query=query,
        status="ok",
        books=[
            _FakeBook("Already Read Novel"),
            _FakeBook("Rejected Novel"),
            _FakeBook("Fresh Novel"),
        ],
        source="test",
        next_action_hint=get_book_search_hint("ok"),
        duration_ms=2,
    )


async def _insert_temp_user_and_thread(
    user_id: uuid.UUID,
    thread_id: uuid.UUID,
) -> None:
    db = get_database()
    async with db.session() as session:
        await session.execute(
            text(
                """
                INSERT INTO public.users (id, display_name, is_mock_user)
                VALUES (:user_id, :display_name, true)
                ON CONFLICT (id) DO NOTHING
                """
            ),
            {"user_id": user_id, "display_name": "Recommendation History Verify"},
        )
        await session.execute(
            text(
                """
                INSERT INTO public.conversations (thread_id, user_id, title)
                VALUES (:thread_id, :user_id, :title)
                ON CONFLICT (thread_id) DO NOTHING
                """
            ),
            {
                "thread_id": thread_id,
                "user_id": user_id,
                "title": "Recommendation History Verify",
            },
        )


async def _delete_temp_user(user_id: uuid.UUID) -> None:
    db = get_database()
    async with db.session() as session:
        await session.execute(
            text("DELETE FROM public.users WHERE id = :user_id"),
            {"user_id": user_id},
        )


async def _seed_history(user_id: uuid.UUID, thread_id: uuid.UUID) -> None:
    db = get_database()
    async with db.session() as session:
        await create_recommendation_event(
            session,
            RecommendationSignalCreate(
                user_id=user_id,
                thread_id=thread_id,
                book_title="Already Read Novel",
                event_type="read",
                signal_polarity="neutral",
                signal_strength=1.0,
                source="book_feedback",
            ),
        )
        await create_recommendation_event(
            session,
            RecommendationSignalCreate(
                user_id=user_id,
                thread_id=thread_id,
                book_title="Rejected Novel",
                event_type="not_interested",
                signal_polarity="negative",
                signal_strength=0.9,
                source="book_feedback",
            ),
        )
        await create_book_interaction(
            session,
            BookInteractionCreate(
                user_id=user_id,
                book_title="Legacy Read Novel",
                interaction_type="read",
            ),
        )


def _titles(records: list[dict]) -> list[str]:
    return [str(item.get("book_title") or item.get("title") or "") for item in records]


async def _verify_turn_policy_and_tool_admission(user_id: uuid.UUID) -> None:
    history_policy = build_turn_policy("What books have I already read?")
    _assert(
        history_policy.intent.primary_intent == "recommendation_history",
        str(history_policy),
    )
    _assert(history_policy.can_view_recommendation_history, str(history_policy))
    _assert(not history_policy.can_search_books, str(history_policy))
    _assert("get_recommendation_history" in history_policy.allowed_tools, str(history_policy))
    _assert("search_books" in history_policy.denied_tools, str(history_policy))

    english_explanation_policy = build_turn_policy(
        "Why did you not recommend Already Read Novel?"
    )
    _assert(
        english_explanation_policy.intent.primary_intent == "recommendation_history",
        str(english_explanation_policy),
    )
    _assert(english_explanation_policy.can_view_recommendation_history, str(english_explanation_policy))
    _assert(not english_explanation_policy.can_search_books, str(english_explanation_policy))
    _assert("get_recommendation_history" in english_explanation_policy.allowed_tools, str(english_explanation_policy))
    _assert("search_books" in english_explanation_policy.denied_tools, str(english_explanation_policy))

    statement_policy = build_turn_policy("I already read Dune.")
    _assert(
        statement_policy.intent.primary_intent == "update_memory",
        str(statement_policy),
    )
    _assert(
        not statement_policy.can_view_recommendation_history,
        str(statement_policy),
    )

    with request_id_scope("verify-history-blocks-book-search"):
        with user_message_scope("What books have I already read?"):
            blocked_search = json.loads(
                await book_tools._search_books_impl("already read books", limit=5)
            )
    _assert(blocked_search["status"] == "intent_blocked", str(blocked_search))
    _assert(
        blocked_search["result_mode"] == "ordinary_recommendation",
        str(blocked_search),
    )

    with request_id_scope("verify-history-tool-blocked-without-intent"):
        with user_message_scope("Please recommend warm novels."):
            blocked_history = json.loads(
                await book_tools._get_recommendation_history_impl(
                    user_id=user_id,
                    history_mode="reading_history",
                    query="read books",
                )
            )
    _assert(blocked_history["status"] == "tool_blocked", str(blocked_history))


async def _verify_history_payload(user_id: uuid.UUID) -> None:
    with request_id_scope("verify-reading-history"):
        with user_message_scope("What books have I already read?"):
            reading = json.loads(
                await book_tools._get_recommendation_history_impl(
                    user_id=user_id,
                    history_mode="reading_history",
                    query="What books have I already read?",
                )
            )
    _assert(reading["status"] == "ok", str(reading))
    _assert(reading["result_mode"] == "recommendation_history", str(reading))
    reading_titles = _titles(reading["records"])
    _assert("Already Read Novel" in reading_titles, str(reading))
    _assert("Legacy Read Novel" in reading_titles, str(reading))
    _assert("Rejected Novel" not in reading_titles, str(reading))

    with request_id_scope("verify-rejection-history"):
        with user_message_scope("Show my not interested records."):
            rejected = json.loads(
                await book_tools._get_recommendation_history_impl(
                    user_id=user_id,
                    history_mode="rejection_history",
                    query="Show my not interested records.",
                )
            )
    _assert("Rejected Novel" in _titles(rejected["records"]), str(rejected))
    _assert("Already Read Novel" not in _titles(rejected["records"]), str(rejected))

    with request_id_scope("verify-suppression-explanation"):
        with user_message_scope("Why didn't you recommend Rejected Novel?"):
            explanation = json.loads(
                await book_tools._get_recommendation_history_impl(
                    user_id=user_id,
                    history_mode="suppression_explanation",
                    query="Why didn't you recommend Rejected Novel?",
                    book_title="Rejected Novel",
                )
            )
    _assert(explanation["status"] == "ok", str(explanation))
    _assert(explanation["suppressed_records"], str(explanation))
    _assert(
        explanation["metadata"]["ordinary_recommendation_candidates"] is False,
        str(explanation),
    )


async def _verify_ordinary_recommendation_suppression(user_id: uuid.UUID) -> None:
    original_search = book_tools.search_and_cache_books_with_status
    try:
        book_tools.search_and_cache_books_with_status = _fake_search
        book_tools.reset_search_books_guard()
        with request_id_scope("verify-ordinary-suppression-still-active"):
            with user_message_scope("Please recommend warm novels."):
                payload = json.loads(
                    await book_tools._search_books_impl(
                        "warm novels",
                        user_id=user_id,
                        limit=5,
                    )
                )
        returned_titles = _titles(payload["books"])
        _assert(returned_titles == ["Fresh Novel"], str(payload))
        suppressed = payload["metadata"]["personalization"]["suppressed_books"]
        suppressed_titles = _titles(suppressed)
        _assert("Already Read Novel" in suppressed_titles, str(payload))
        _assert("Rejected Novel" in suppressed_titles, str(payload))
    finally:
        book_tools.search_and_cache_books_with_status = original_search
        book_tools.reset_search_books_guard()


async def _run_history_flow() -> None:
    user_id = uuid.uuid4()
    thread_id = uuid.uuid4()
    await _insert_temp_user_and_thread(user_id, thread_id)
    try:
        await _seed_history(user_id, thread_id)
        await _verify_turn_policy_and_tool_admission(user_id)
        await _verify_history_payload(user_id)
        await _verify_ordinary_recommendation_suppression(user_id)
    finally:
        await _delete_temp_user(user_id)


async def _main(skip_migration: bool) -> None:
    load_dotenv()
    if not skip_migration:
        _init_postgres()
    init_embedding_model()
    await init_database()
    try:
        await _run_history_flow()
    finally:
        await dispose_database()
    print("recommendation history verification passed")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-migration", action="store_true")
    args = parser.parse_args()

    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(_main(skip_migration=args.skip_migration))


if __name__ == "__main__":
    main()
