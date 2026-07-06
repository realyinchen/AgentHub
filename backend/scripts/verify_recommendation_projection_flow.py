"""Verify Phase P2 recommendation projection and scoring.

This check uses local PostgreSQL and no external network. It verifies:
- projection ranks candidates using memory/profile preferences
- read and negative feedback suppress candidates
- attention signals decay over time and do not write long-term memory
- search_books returns projected scores and suppression metadata
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
from app.crud.book import create_recommendation_event, update_preference_profile
from app.infra.database import dispose_database, get_database, init_database
from app.infra.llm.embedding import init_embedding_model
from app.schemas.book import UserPreferenceProfileUpdate
from app.services.book_search import BookSearchCacheResult
from app.services.book_search_contracts import get_book_search_hint
from app.services.recommendation_projection import RecommendationProjector
from app.services.recommendation_signals import RecommendationSignalCreate
from app.utils.logging import request_id_scope
from app.utils.turn_context import user_message_scope
from scripts.init_database import _init_postgres


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


class _FakeBook:
    def __init__(
        self,
        *,
        title: str,
        authors: list[str] | None = None,
        tags: list[str] | None = None,
        summary: str = "",
    ) -> None:
        self.id = uuid.uuid4()
        self.title = title
        self.subtitle = None
        self.authors = authors or ["Example Author"]
        self.tags = tags or []
        self.summary = summary
        self.rating = None
        self.source_name = "test"
        self.source_url = f"https://example.test/{self.id}"
        self.external_id = str(self.id)
        self.raw_data = {}


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
            {"user_id": user_id, "display_name": "Recommendation Projection Verify"},
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
                "title": "Recommendation Projection Verify",
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


async def _set_event_age(event_id: uuid.UUID, *, days_old: int) -> None:
    db = get_database()
    async with db.session() as session:
        await session.execute(
            text(
                """
                UPDATE public.recommendation_events
                SET created_at = NOW() - (CAST(:days_old AS integer) * INTERVAL '1 day'),
                    updated_at = NOW() - (CAST(:days_old AS integer) * INTERVAL '1 day')
                WHERE id = :event_id
                """
            ),
            {"event_id": event_id, "days_old": days_old},
        )


def _candidate_by_title(payload: dict, title: str) -> dict | None:
    for item in payload.get("books", []):
        if item.get("title") == title:
            return item
    return None


async def _fake_search(session, *, query: str, limit: int) -> BookSearchCacheResult:
    return BookSearchCacheResult(
        query=query,
        status="ok",
        books=[
            _FakeBook(
                title="Already Read Novel",
                tags=["warm"],
                summary="A warm novel the user already finished.",
            ),
            _FakeBook(
                title="Bloody Thriller",
                tags=["bloody"],
                summary="A bloody dark thriller.",
            ),
            _FakeBook(
                title="Fresh Warm Novel",
                tags=["warm"],
                summary="A warm character-driven family story.",
            ),
        ],
        source="test",
        next_action_hint=get_book_search_hint("ok"),
        duration_ms=3,
    )


async def _run_projection_flow() -> None:
    user_id = uuid.uuid4()
    thread_id = uuid.uuid4()
    warm_book = _FakeBook(
        title="Fresh Warm Novel",
        tags=["warm"],
        summary="A warm character-driven family story.",
    )
    bloody_book = _FakeBook(
        title="Bloody Thriller",
        tags=["bloody"],
        summary="A bloody dark thriller.",
    )
    read_book = _FakeBook(
        title="Already Read Novel",
        tags=["warm"],
        summary="A warm novel the user already finished.",
    )
    recent_attention_book = _FakeBook(
        title="Recent Attention Novel",
        summary="A quiet novel with characters the user kept asking about.",
    )
    old_attention_book = _FakeBook(
        title="Old Attention Novel",
        summary="A quiet novel with characters the user once asked about.",
    )

    original_search = book_tools.search_and_cache_books_with_status
    await _insert_temp_user_and_thread(user_id, thread_id)
    try:
        db = get_database()
        async with db.session() as session:
            await update_preference_profile(
                session,
                user_id,
                UserPreferenceProfileUpdate(
                    preferred_tags=["warm"],
                    disliked_tags=["bloody"],
                ),
            )
            await create_recommendation_event(
                session,
                RecommendationSignalCreate(
                    user_id=user_id,
                    book_title="Already Read Novel",
                    event_type="read",
                    signal_polarity="neutral",
                    signal_strength=1.0,
                    source="system",
                ),
            )
            recent = await create_recommendation_event(
                session,
                RecommendationSignalCreate(
                    user_id=user_id,
                    book_title="Recent Attention Novel",
                    event_type="detail_requested",
                    signal_polarity="positive",
                    signal_strength=1.0,
                    source="followup_question",
                ),
            )
            old = await create_recommendation_event(
                session,
                RecommendationSignalCreate(
                    user_id=user_id,
                    book_title="Old Attention Novel",
                    event_type="detail_requested",
                    signal_polarity="positive",
                    signal_strength=1.0,
                    source="followup_question",
                ),
            )
        await _set_event_age(old.id, days_old=90)

        before_memory_count = await _memory_event_count(user_id)
        db = get_database()
        async with db.session() as session:
            projection = await RecommendationProjector(session).project_books(
                user_id=user_id,
                query="warm character driven novels",
                books=[
                    bloody_book,
                    warm_book,
                    read_book,
                    old_attention_book,
                    recent_attention_book,
                ],
            )

        _assert(
            await _memory_event_count(user_id) == before_memory_count,
            "projection must not write long-term memory",
        )
        titles = [candidate.book_title for candidate in projection.candidates]
        _assert("Already Read Novel" not in titles, titles)
        _assert(
            projection.suppressed_candidates
            and projection.suppressed_candidates[0].book_title == "Already Read Novel",
            str(projection),
        )
        _assert(
            titles.index("Fresh Warm Novel") < titles.index("Bloody Thriller"),
            titles,
        )
        recent_projection = next(
            item for item in projection.candidates if item.book_title == "Recent Attention Novel"
        )
        old_projection = next(
            item for item in projection.candidates if item.book_title == "Old Attention Novel"
        )
        _assert(
            recent_projection.behavior_score > old_projection.behavior_score,
            f"recent={recent_projection.behavior_score} old={old_projection.behavior_score}",
        )

        book_tools.search_and_cache_books_with_status = _fake_search
        book_tools.reset_search_books_guard()
        with request_id_scope("verify-projected-search"):
            with user_message_scope("Please recommend warm character driven novels."):
                payload = json.loads(
                    await book_tools._search_books_impl(
                        "warm character driven novels",
                        user_id=user_id,
                        limit=5,
                    )
                )

        returned_titles = [item["title"] for item in payload["books"]]
        _assert("Already Read Novel" not in returned_titles, str(payload))
        _assert(returned_titles[0] == "Fresh Warm Novel", returned_titles)
        warm_payload = _candidate_by_title(payload, "Fresh Warm Novel")
        _assert(warm_payload is not None, str(payload))
        assert warm_payload is not None
        _assert("recommendation" in warm_payload, str(warm_payload))
        _assert(
            payload["metadata"]["personalization"]["projection"]["metadata"][
                "contract_version"
            ]
            == "recommendation-projection-v1",
            str(payload),
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
        await _run_projection_flow()
    finally:
        await dispose_database()
    print("recommendation projection verification passed")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-migration", action="store_true")
    args = parser.parse_args()

    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(_main(skip_migration=args.skip_migration))


if __name__ == "__main__":
    main()
