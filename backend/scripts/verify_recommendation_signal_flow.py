"""Verify Phase P recommendation behavior signals.

This check uses local PostgreSQL and no external network. It verifies:
- recommendation_events is separate from long-term memory
- book feedback writes both recommendation state and admitted memory
- detail/attention signals do not write long-term memory
- search_books suppresses already-read or negative-feedback titles when user_id is passed
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
from app.crud.book import create_recommendation_event, get_suppressed_book_titles
from app.infra.database import dispose_database, get_database, init_database
from app.infra.llm.embedding import init_embedding_model
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
    def __init__(self, *, book_id: uuid.UUID, title: str) -> None:
        self.id = book_id
        self.title = title
        self.authors = ["Example Author"]
        self.summary = "A warm, character-driven example novel."
        self.rating = None
        self.source_name = "test"
        self.source_url = f"https://example.test/{book_id}"
        self.external_id = str(book_id)


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
            {"user_id": user_id, "display_name": "Recommendation Signal Verify"},
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
                "title": "Recommendation Signal Verify",
            },
        )


async def _insert_temp_book(book_id: uuid.UUID, title: str) -> None:
    db = get_database()
    async with db.session() as session:
        await session.execute(
            text(
                """
                INSERT INTO public.books (id, title, authors, source_name, source_url)
                VALUES (:book_id, :title, '["Example Author"]'::jsonb, 'test', :url)
                ON CONFLICT (id) DO NOTHING
                """
            ),
            {
                "book_id": book_id,
                "title": title,
                "url": f"https://example.test/{book_id}",
            },
        )


async def _delete_temp_user(user_id: uuid.UUID) -> None:
    db = get_database()
    async with db.session() as session:
        await session.execute(
            text("DELETE FROM public.users WHERE id = :user_id"),
            {"user_id": user_id},
        )


async def _memory_event_count(user_id: uuid.UUID) -> int:
    db = get_database()
    async with db.session() as session:
        count = await session.scalar(
            text("SELECT COUNT(*) FROM public.memory_events WHERE user_id = :user_id"),
            {"user_id": user_id},
        )
        return int(count or 0)


async def _recommendation_event_count(user_id: uuid.UUID) -> int:
    db = get_database()
    async with db.session() as session:
        count = await session.scalar(
            text(
                "SELECT COUNT(*) FROM public.recommendation_events WHERE user_id = :user_id"
            ),
            {"user_id": user_id},
        )
        return int(count or 0)


async def _fake_search(session, *, query: str, limit: int) -> BookSearchCacheResult:
    return BookSearchCacheResult(
        query=query,
        status="ok",
        books=[
            _FakeBook(book_id=uuid.uuid4(), title="Already Read Novel"),
            _FakeBook(book_id=uuid.uuid4(), title="Fresh Warm Novel"),
        ],
        source="test",
        next_action_hint=get_book_search_hint("ok"),
        duration_ms=3,
    )


async def _run_flow() -> None:
    user_id = uuid.uuid4()
    thread_id = uuid.uuid4()
    read_book_id = uuid.uuid4()

    original_search = book_tools.search_and_cache_books_with_status
    await _insert_temp_user_and_thread(user_id, thread_id)
    await _insert_temp_book(read_book_id, "Already Read Novel")

    try:
        initial_memory_count = await _memory_event_count(user_id)
        initial_signal_count = await _recommendation_event_count(user_id)

        with request_id_scope("verify-book-feedback-signal"):
            with user_message_scope("I already read Already Read Novel."):
                feedback = json.loads(
                    await book_tools.record_book_feedback.ainvoke(
                        {
                            "user_id": user_id,
                            "thread_id": thread_id,
                            "book_title": "Already Read Novel",
                            "interaction_type": "read",
                            "note": "finished it",
                        }
                    )
                )

        _assert(feedback["recommendation_event"]["event_type"] == "read", str(feedback))
        _assert(feedback["recommendation_event"]["source"] == "book_feedback", str(feedback))
        _assert(await _memory_event_count(user_id) > initial_memory_count, "feedback writes memory")
        _assert(
            await _recommendation_event_count(user_id) > initial_signal_count,
            "feedback writes recommendation event",
        )

        memory_after_feedback = await _memory_event_count(user_id)
        with request_id_scope("verify-detail-signal"):
            with user_message_scope("Tell me more about Already Read Novel."):
                detail_signal = json.loads(
                    await book_tools.record_recommendation_signal.ainvoke(
                        {
                            "user_id": user_id,
                            "thread_id": thread_id,
                            "book_title": "Already Read Novel",
                            "event_type": "detail_requested",
                            "signal_polarity": "positive",
                            "signal_strength": 0.55,
                            "note": "attention without durable preference",
                        }
                    )
                )

        _assert(
            detail_signal["recommendation_event"]["event_type"] == "detail_requested",
            str(detail_signal),
        )
        _assert(
            await _memory_event_count(user_id) == memory_after_feedback,
            "attention signal must not write long-term memory",
        )

        db = get_database()
        async with db.session() as session:
            await create_recommendation_event(
                session,
                RecommendationSignalCreate(
                    user_id=user_id,
                    book_title="Suppressed By Event",
                    event_type="not_interested",
                    signal_polarity="negative",
                    signal_strength=0.8,
                    source="system",
                ),
            )
            suppressed = await get_suppressed_book_titles(session, user_id=user_id)
            _assert("already read novel" in suppressed, "read title should suppress")
            _assert("suppressed by event" in suppressed, "negative event should suppress")

        book_tools.search_and_cache_books_with_status = _fake_search
        book_tools.reset_search_books_guard()
        with request_id_scope("verify-search-suppression"):
            with user_message_scope("Please recommend warm novels."):
                search_payload = json.loads(
                    await book_tools._search_books_impl(
                        "warm novels",
                        limit=5,
                        user_id=user_id,
                    )
                )

        returned_titles = {book["title"] for book in search_payload["books"]}
        _assert("Already Read Novel" not in returned_titles, str(search_payload))
        _assert("Fresh Warm Novel" in returned_titles, str(search_payload))
        _assert(len(search_payload["follow_up_questions"]) == 3, str(search_payload))
        _assert(
            search_payload["metadata"]["personalization"]["suppressed_books"],
            "suppressed titles should be reported in metadata",
        )

    finally:
        book_tools.search_and_cache_books_with_status = original_search
        book_tools.reset_search_books_guard()
        await _delete_temp_user(user_id)


async def _main(skip_migration: bool) -> None:
    load_dotenv()
    if not skip_migration:
        _init_postgres()
    init_embedding_model()
    await init_database()
    try:
        await _run_flow()
    finally:
        await dispose_database()
    print("recommendation signal verification passed")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-migration", action="store_true")
    args = parser.parse_args()

    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(_main(skip_migration=args.skip_migration))


if __name__ == "__main__":
    main()
