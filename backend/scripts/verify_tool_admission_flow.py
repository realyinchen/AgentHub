"""
Verify Phase N ToolAdmissionGate boundaries.

This check avoids network and LLM calls. It verifies:
- tool calls are admitted by app-owned turn policy, not by agent preference
- ordinary recommendation search is limited to one search per turn
- memory writes and forgetting require explicit memory policy flags
- research tools require Deep Search / Deep Research intent
- research tools are not constrained by ordinary recommendation search budgets

Usage:
    cd backend
    .\\.venv\\Scripts\\python.exe scripts\\verify_tool_admission_flow.py
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import uuid
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from sqlalchemy import text

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.agents.tools import books as book_tools
from app.agents.tools import memory as memory_tools
from app.agents.tools import research as research_tools
from app.infra.database import dispose_database, get_database, init_database
from app.infra.llm.embedding import init_embedding_model
from app.services.book_intent import build_turn_policy
from app.services.book_search import BookSearchCacheResult
from app.services.book_search_contracts import get_book_search_hint
from app.services.tool_admission import reset_tool_admission_gate
from app.utils.logging import request_id_scope
from app.utils.turn_context import user_message_scope
from scripts.init_database import _init_postgres


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


class _FakeSessionContext:
    async def __aenter__(self) -> object:
        return object()

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None


class _FakeDatabase:
    def session(self) -> _FakeSessionContext:
        return _FakeSessionContext()


class _FakeBook:
    def __init__(self, title: str) -> None:
        self.id = uuid.uuid4()
        self.title = title
        self.authors = ["Example Author"]
        self.summary = "A warm, character-driven example novel."
        self.rating = None
        self.source_name = "test"
        self.source_url = "https://example.test/book"
        self.external_id = "example-book"


async def _fake_ok_search(
    session,
    *,
    query: str,
    limit: int,
) -> BookSearchCacheResult:
    return BookSearchCacheResult(
        query=query,
        status="ok",
        books=[_FakeBook("Example Novel")],
        source="test",
        next_action_hint=get_book_search_hint("ok"),
        duration_ms=1,
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
            {"user_id": user_id, "display_name": "Tool Admission Verify"},
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
                "title": "Tool Admission Verify",
            },
        )


async def _delete_temp_user(user_id: uuid.UUID) -> None:
    db = get_database()
    async with db.session() as session:
        await session.execute(
            text("DELETE FROM public.users WHERE id = :user_id"),
            {"user_id": user_id},
        )


async def _remember_memory(**payload: Any) -> dict[str, Any]:
    return json.loads(await memory_tools.remember_memory.ainvoke(payload))


async def _forget_memory(**payload: Any) -> dict[str, Any]:
    return json.loads(await memory_tools.forget_memory.ainvoke(payload))


async def _start_research(**payload: Any) -> dict[str, Any]:
    return json.loads(await research_tools.start_research.ainvoke(payload))


async def _search_research(**payload: Any) -> dict[str, Any]:
    return json.loads(await research_tools.search_research.ainvoke(payload))


async def _verify_book_search_admission() -> None:
    original_get_database = book_tools.get_database
    original_search = book_tools.search_and_cache_books_with_status
    search_call_count = 0

    async def counted_search(session, *, query: str, limit: int):
        nonlocal search_call_count
        search_call_count += 1
        return await _fake_ok_search(session, query=query, limit=limit)

    book_tools.get_database = lambda: _FakeDatabase()
    book_tools.search_and_cache_books_with_status = counted_search
    try:
        recommendation_policy = build_turn_policy(
            "Please recommend warm character-driven novels."
        )
        _assert(
            "search_memory" in recommendation_policy.allowed_tools,
            "recommendation turns may read memory",
        )
        _assert(
            "remember_memory" in recommendation_policy.denied_tools,
            "recommendation turns must not advertise memory writes",
        )
        _assert(
            "revise_memory" in recommendation_policy.denied_tools,
            "recommendation turns must not advertise memory revisions",
        )
        _assert(
            "forget_memory" in recommendation_policy.denied_tools,
            "recommendation turns must not advertise memory deletion",
        )

        reset_tool_admission_gate()
        with request_id_scope("phase-n-style-question-blocks-book-search"):
            with user_message_scope(
                "I like Nonviolent Communication. What is this book style?"
            ):
                blocked = json.loads(
                    await book_tools._search_books_impl(
                        "books like Nonviolent Communication",
                        limit=5,
                    )
                )
        _assert(blocked["status"] == "intent_blocked", "style question should block")
        _assert(search_call_count == 0, "blocked search must not call provider")
        admission = blocked["metadata"]["tool_admission"]
        _assert(
            admission["reason"] == "required_policy_flags_missing",
            "blocked search should report missing policy flag",
        )
        _assert(
            "can_search_books" in admission["metadata"]["missing_policy_flags"],
            "book search should require can_search_books",
        )

        reset_tool_admission_gate()
        with request_id_scope("phase-n-ordinary-book-search-budget"):
            with user_message_scope("Please recommend warm character-driven novels."):
                first = json.loads(
                    await book_tools._search_books_impl("warm character novels", limit=3)
                )
                second = json.loads(
                    await book_tools._search_books_impl("gentle family novels", limit=3)
                )
        _assert(first["status"] == "ok", "first ordinary search should be allowed")
        _assert(second["status"] == "loop_detected", "second search should be blocked")
        _assert(
            second["metadata"]["tool_admission"]["reason"] == "tool_budget_exhausted",
            "second search should report budget exhaustion",
        )
    finally:
        book_tools.get_database = original_get_database
        book_tools.search_and_cache_books_with_status = original_search
        reset_tool_admission_gate()


async def _verify_memory_admission(user_id: uuid.UUID) -> None:
    reset_tool_admission_gate()
    with request_id_scope("phase-n-memory-write-blocked"):
        with user_message_scope("What is the style of Nonviolent Communication?"):
            remembered = await _remember_memory(
                user_id=str(user_id),
                type="preference",
                subject="style",
                value="nonviolent communication",
                polarity="like",
                source_text="What is the style of Nonviolent Communication?",
            )
    _assert(remembered["status"] == "tool_blocked", "memory write should block")
    _assert(
        "can_write_memory"
        in remembered["tool_admission"]["metadata"]["missing_policy_flags"],
        "remember_memory should require can_write_memory",
    )

    reset_tool_admission_gate()
    with request_id_scope("phase-n-memory-forget-blocked"):
        with user_message_scope("Please recommend warm character-driven novels."):
            forgotten = await _forget_memory(
                user_id=str(user_id),
                subject="style",
                value="bloody suspense",
                memory_type="preference",
                reason="verify blocked forgetting",
            )
    _assert(forgotten["status"] == "tool_blocked", "forget should block")
    _assert(forgotten["forgotten_count"] == 0, "blocked forget must not delete memory")
    _assert(
        "can_manage_memory"
        in forgotten["tool_admission"]["metadata"]["missing_policy_flags"],
        "forget_memory should require can_manage_memory",
    )


async def _verify_research_admission(
    user_id: uuid.UUID,
    thread_id: uuid.UUID,
) -> None:
    reset_tool_admission_gate()
    with request_id_scope("phase-n-research-start-blocked"):
        with user_message_scope("What is the style of Nonviolent Communication?"):
            blocked = await _start_research(
                user_id=str(user_id),
                thread_id=str(thread_id),
                objective="Research a style question without explicit deep intent.",
            )
    _assert(blocked["status"] == "tool_blocked", "non-research turn should block")
    _assert(
        "can_start_research"
        in blocked["tool_admission"]["metadata"]["missing_policy_flags"],
        "start_research should require can_start_research",
    )

    reset_tool_admission_gate()
    with request_id_scope("phase-n-research-tools-not-book-budgeted"):
        with user_message_scope(
            "Please deep research warm communication books and compare evidence."
        ):
            started = await _start_research(
                user_id=str(user_id),
                thread_id=str(thread_id),
                objective="Deep research warm communication books.",
                subquestions=["Which books are warm and communication-oriented?"],
                gaps=["Need source-backed candidate facts."],
                next_actions=["Search two distinct evidence points."],
                budget={"max_steps": 5},
                stop_criteria=["Two research search steps recorded."],
            )
            run_id = started["run"]["id"]
            first = await _search_research(
                user_id=str(user_id),
                run_id=run_id,
                query="warm communication books source one",
                status="completed",
                rationale="First research query.",
                results=[{"title": "Source One", "url": "https://example.test/one"}],
                next_actions=["Search a second evidence point."],
            )
            second = await _search_research(
                user_id=str(user_id),
                run_id=run_id,
                query="warm communication books source two",
                status="completed",
                rationale="Second research query.",
                results=[{"title": "Source Two", "url": "https://example.test/two"}],
                next_actions=["Aggregate evidence."],
            )
    _assert(started["run"]["status"] == "active", "research should start")
    _assert(first["state"]["status"] == "active", "first research search should pass")
    _assert(second["state"]["status"] == "active", "second research search should pass")
    _assert(
        len([step for step in second["steps"] if step["step_type"] == "search"]) >= 2,
        "research tools should allow repeated search-state updates",
    )


async def _run_tool_admission_flow() -> None:
    user_id = uuid.uuid4()
    thread_id = uuid.uuid4()

    await _insert_temp_user_and_thread(user_id, thread_id)
    try:
        await _verify_book_search_admission()
        await _verify_memory_admission(user_id)
        await _verify_research_admission(user_id, thread_id)
        print("tool admission verification passed")
        print(f"user_id={user_id}")
        print(f"thread_id={thread_id}")
    finally:
        await _delete_temp_user(user_id)


async def _main(skip_migration: bool) -> None:
    load_dotenv()
    if not skip_migration:
        _init_postgres()
    init_embedding_model()
    await init_database()
    try:
        await _run_tool_admission_flow()
    finally:
        await dispose_database()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--skip-migration",
        action="store_true",
        help="Skip SQL migration and only run behavior checks.",
    )
    args = parser.parse_args()

    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(_main(skip_migration=args.skip_migration))


if __name__ == "__main__":
    main()
