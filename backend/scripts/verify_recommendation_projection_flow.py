"""Verify Phase P2 recommendation projection and scoring.

This check uses local PostgreSQL and no external network. It verifies:
- projection ranks candidates using app-owned current memory preferences
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
from app.crud.book import create_recommendation_event
from app.infra.database import dispose_database, get_database, init_database
from app.infra.llm.embedding import init_embedding_model
from app.services.book_search import BookSearchCacheResult
from app.services.book_search_contracts import get_book_search_hint
from app.services.memory.contracts import MemoryCandidate
from app.services.memory.orchestrator import get_memory_orchestrator
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


async def _clear_legacy_preference_profile(user_id: uuid.UUID) -> None:
    db = get_database()
    async with db.session() as session:
        await session.execute(
            text(
                """
                UPDATE public.user_preference_profiles
                SET preferred_tags = '[]'::jsonb,
                    disliked_tags = '[]'::jsonb,
                    favorite_authors = '[]'::jsonb,
                    disliked_authors = '[]'::jsonb,
                    profile_summary = '',
                    notes = ''
                WHERE user_id = :user_id
                """
            ),
            {"user_id": user_id},
        )


def _candidate_by_title(payload: dict, title: str) -> dict | None:
    for item in payload.get("books", []):
        if item.get("title") == title:
            return item
    return None


async def _fake_search(session, *, query: str, limit: int) -> BookSearchCacheResult:
    already_read = _FakeBook(
        title="Already Read Novel",
        tags=["warm"],
        summary="A warm novel the user already finished.",
    )
    bloody = _FakeBook(
        title="Bloody Thriller",
        tags=["bloody"],
        summary="A bloody dark thriller.",
    )
    fresh = _FakeBook(
        title="Fresh Warm Novel",
        tags=["warm"],
        summary="A warm character-driven family story.",
    )
    books = [already_read, bloody, fresh]
    return BookSearchCacheResult(
        query=query,
        status="ok",
        books=books,
        source="test",
        next_action_hint=get_book_search_hint("ok"),
        duration_ms=3,
        candidate_sources={
            str(already_read.id): {
                "candidate_source": "book_cache",
                "source": "book_cache",
                "rank_index": 0,
                "match_score": 4.0,
                "reason": "candidate matched local Book Cache before external search",
            },
            str(bloody.id): {
                "candidate_source": "external_search",
                "source": "test_search",
                "rank_index": 1,
                "provider_status": "ok",
                "reason": "candidate was added from external book search",
            },
            str(fresh.id): {
                "candidate_source": "book_cache",
                "source": "book_cache",
                "rank_index": 2,
                "match_score": 8.0,
                "reason": "candidate matched local Book Cache before external search",
            },
        },
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
    cache_source_book = _FakeBook(
        title="Cache Source Novel",
        tags=["source"],
        summary="A quiet source novel from the local cache.",
    )
    external_source_book = _FakeBook(
        title="External Source Novel",
        tags=["source"],
        summary="A quiet source novel from external search.",
    )

    original_search = book_tools.search_and_cache_books_with_status
    await _insert_temp_user_and_thread(user_id, thread_id)
    try:
        orchestrator = get_memory_orchestrator()
        warm_memory = await orchestrator.remember_candidate(
            MemoryCandidate(
                user_id=user_id,
                thread_id=thread_id,
                type="preference",
                subject="style",
                value="warm character-driven novels",
                polarity="like",
                confidence=0.95,
                source_text="Recommend warm character-driven novels.",
                source_kind="user_message",
                metadata={"origin": "verify_recommendation_projection_flow"},
            )
        )
        bloody_memory = await orchestrator.remember_candidate(
            MemoryCandidate(
                user_id=user_id,
                thread_id=thread_id,
                type="preference",
                subject="content",
                value="bloody or too dark suspense",
                polarity="avoid",
                confidence=0.95,
                source_text="I do not want bloody or too dark suspense.",
                source_kind="user_message",
                metadata={"origin": "verify_recommendation_projection_flow"},
            )
        )
        _assert(
            warm_memory.memory is not None and bloody_memory.memory is not None,
            "memory preferences must be admitted before recommendation projection",
        )
        await _clear_legacy_preference_profile(user_id)

        db = get_database()
        async with db.session() as session:
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
        _assert(
            projection.metadata["preference_source"] == "current_memory",
            str(projection.metadata),
        )
        _assert(
            not projection.metadata["legacy_profile_fallback_used"],
            str(projection.metadata),
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

        async with db.session() as session:
            source_projection = await RecommendationProjector(session).project_books(
                user_id=user_id,
                query="quiet source novels",
                books=[external_source_book, cache_source_book],
                candidate_sources={
                    str(external_source_book.id): {
                        "candidate_source": "external_search",
                        "source": "test_search",
                        "rank_index": 0,
                        "provider_status": "ok",
                    },
                    str(cache_source_book.id): {
                        "candidate_source": "book_cache",
                        "source": "book_cache",
                        "rank_index": 1,
                        "match_score": 8.0,
                    },
                },
            )
        source_titles = [candidate.book_title for candidate in source_projection.candidates]
        _assert(source_titles[0] == "Cache Source Novel", source_titles)
        cache_projection = source_projection.candidates[0]
        _assert(cache_projection.source_score > 0, str(cache_projection))
        _assert(
            any(feature.source == "candidate_source" for feature in cache_projection.features),
            str(cache_projection.features),
        )
        _assert(
            source_projection.metadata["candidate_source_scoring"] == "enabled",
            str(source_projection.metadata),
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
        explanation = warm_payload["recommendation_explanation"]
        _assert(
            explanation["contract_version"] == "recommendation-explanation-v1",
            str(explanation),
        )
        _assert(
            explanation["features"]["long_term_memory"],
            str(explanation),
        )
        _assert(
            explanation["score_breakdown"]["memory_score"] > 0,
            str(explanation),
        )
        _assert(
            explanation["score_breakdown"]["source_score"] > 0,
            str(explanation),
        )
        _assert(
            explanation["features"]["candidate_source"],
            str(explanation),
        )
        _assert(
            payload["metadata"]["personalization"]["projection"]["metadata"][
                "contract_version"
            ]
            == "recommendation-projection-v1",
            str(payload),
        )
        _assert(
            payload["metadata"]["personalization"]["projection"]["metadata"][
                "preference_source"
            ]
            == "current_memory",
            str(payload),
        )
        constraints = payload["metadata"]["personalization"]["constraints"]
        _assert(
            constraints["metadata"]["constraint_source"] == "current_memory",
            str(constraints),
        )
        _assert(
            "warm character-driven novels" in constraints["preferred_terms"],
            str(constraints),
        )
        _assert(
            "bloody or too dark suspense" in constraints["avoided_terms"],
            str(constraints),
        )

        book_tools.reset_search_books_guard()
        with request_id_scope("verify-personalized-search-query"):
            with user_message_scope("Please recommend some novels."):
                personalized_payload = json.loads(
                    await book_tools._search_books_impl(
                        "novels",
                        user_id=user_id,
                        limit=5,
                    )
                )

        personalized_constraints = personalized_payload["metadata"][
            "personalization"
        ]["constraints"]
        _assert(
            personalized_constraints["applied_to_search"],
            str(personalized_constraints),
        )
        _assert(
            "warm character-driven novels"
            in personalized_constraints["search_terms_added"],
            str(personalized_constraints),
        )
        _assert(
            personalized_payload["effective_query"]
            == personalized_payload["metadata"]["search"]["effective_query"],
            str(personalized_payload),
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
