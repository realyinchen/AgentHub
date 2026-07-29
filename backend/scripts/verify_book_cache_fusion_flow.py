"""Verify ordinary Book Search / Book Cache candidate fusion.

This check avoids live network calls. It verifies:
- local cache hits can satisfy an ordinary search without external search
- external search tops up missing candidates when cache is insufficient
- search_books exposes cache/source fusion metadata
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import text

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.agents.tools import books as book_tools
from app.crud.book import upsert_book
from app.infra.database import dispose_database, get_database, init_database
from app.infra.llm.embedding import init_embedding_model
from app.services import book_search
from app.services.book_search_contracts import BookCandidateSearchResult
from app.utils.logging import request_id_scope
from app.utils.turn_context import user_message_scope
from scripts.init_database import _init_postgres


TEST_URL_PREFIX = "https://example.test/cache-fusion/"


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


async def _cleanup_books() -> None:
    db = get_database()
    async with db.session() as session:
        await session.execute(
            text("DELETE FROM public.books WHERE source_url LIKE :pattern"),
            {"pattern": f"{TEST_URL_PREFIX}%"},
        )


async def _seed_cached_book() -> None:
    db = get_database()
    async with db.session() as session:
        await upsert_book(
            session,
            {
                "title": "Cached Warm Family Novel",
                "authors": ["Cache Author"],
                "tags": ["warm", "character-driven"],
                "summary": "A warm character driven family story from cache.",
                "source_name": "test_cache",
                "source_url": f"{TEST_URL_PREFIX}cached-warm",
                "external_id": "cached-warm",
                "raw_data": {"origin": "verify_book_cache_fusion_flow"},
            },
        )


async def _run_cache_fusion_flow() -> None:
    call_count = 0
    original_service_search = book_search.search_external_book_candidates
    original_tool_search = book_tools.search_and_cache_books_with_status

    async def fake_external_search(
        query: str,
        limit: int = 5,
    ) -> BookCandidateSearchResult:
        nonlocal call_count
        call_count += 1
        return BookCandidateSearchResult(
            query=query,
            provider_query=f"fake:{query}",
            status="ok",
            candidates=[
                {
                    "title": "External Fresh Warm Novel",
                    "authors": ["External Author"],
                    "tags": ["warm"],
                    "summary": "A warm character driven story from external search.",
                    "source_name": "test_search",
                    "source_url": f"{TEST_URL_PREFIX}external-fresh",
                    "external_id": "external-fresh",
                    "raw_data": {"origin": "verify_book_cache_fusion_flow"},
                }
            ][:limit],
            source="test_search",
            duration_ms=2,
        )

    await _cleanup_books()
    await _seed_cached_book()
    try:
        book_search.search_external_book_candidates = fake_external_search
        book_tools.search_and_cache_books_with_status = (
            book_search.search_and_cache_books_with_status
        )

        db = get_database()
        async with db.session() as session:
            cache_only = await book_search.search_and_cache_books_with_status(
                session,
                query="warm character driven novels",
                limit=1,
            )
        _assert(cache_only.status == "ok", str(cache_only))
        _assert(cache_only.source == "book_cache", str(cache_only))
        _assert(call_count == 0, f"external search should not run: {call_count}")
        _assert(
            cache_only.metadata["external_search_performed"] is False,
            str(cache_only.metadata),
        )
        _assert(
            cache_only.books[0].title == "Cached Warm Family Novel",
            [book.title for book in cache_only.books],
        )
        cache_source = cache_only.candidate_sources[str(cache_only.books[0].id)]
        _assert(cache_source["candidate_source"] == "book_cache", str(cache_source))

        db = get_database()
        async with db.session() as session:
            fused = await book_search.search_and_cache_books_with_status(
                session,
                query="warm character driven novels",
                limit=2,
            )
        fused_titles = [book.title for book in fused.books]
        _assert(fused.status == "ok", str(fused))
        _assert(fused.source == "book_cache+test_search", str(fused))
        _assert(call_count == 1, f"external search should top up once: {call_count}")
        _assert(
            fused.metadata["cache_hit_count"] == 1
            and fused.metadata["external_search_performed"],
            str(fused.metadata),
        )
        _assert(
            fused_titles == ["Cached Warm Family Novel", "External Fresh Warm Novel"],
            str(fused_titles),
        )
        fused_sources = [
            fused.candidate_sources[str(book.id)]["candidate_source"]
            for book in fused.books
        ]
        _assert(
            fused_sources == ["book_cache", "external_search"],
            str(fused.candidate_sources),
        )

        book_tools.reset_search_books_guard()
        with request_id_scope("verify-book-cache-tool-metadata"):
            with user_message_scope("Please recommend warm character driven novels."):
                payload = json.loads(
                    await book_tools._search_books_impl(
                        "warm character driven novels",
                        limit=2,
                    )
                )

        cache_metadata = payload["metadata"]["search"]["cache"]
        _assert(
            cache_metadata["contract_version"] == "book-cache-fusion-v1",
            str(cache_metadata),
        )
        _assert(
            cache_metadata["cache_hit_count"] >= 1,
            str(cache_metadata),
        )
        _assert(payload["source"] == "book_cache", str(payload))
        first_book = payload["books"][0]
        _assert(
            first_book["candidate_source"]["candidate_source"] == "book_cache",
            str(first_book),
        )
        _assert(
            first_book["recommendation_explanation"]["contract_version"]
            == "recommendation-explanation-v1",
            str(first_book),
        )
        _assert(
            "book_cache"
            in first_book["recommendation_explanation"]["contribution_sources"],
            str(first_book),
        )

    finally:
        book_tools.search_and_cache_books_with_status = original_tool_search
        book_search.search_external_book_candidates = original_service_search
        book_tools.reset_search_books_guard()
        await _cleanup_books()


async def _main(skip_migration: bool) -> None:
    load_dotenv()
    if not skip_migration:
        _init_postgres()
    init_embedding_model()
    await init_database()
    try:
        await _run_cache_fusion_flow()
    finally:
        await dispose_database()
    print("book cache fusion verification passed")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-migration", action="store_true")
    args = parser.parse_args()

    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(_main(skip_migration=args.skip_migration))


if __name__ == "__main__":
    main()
