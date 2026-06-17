"""
Verify the app-owned memory contract against a local PostgreSQL database.

Usage:
    cd backend
    .\\.venv\\Scripts\\python.exe scripts\\verify_memory_flow.py

The script runs idempotent SQL migrations, creates a temporary user and two
temporary conversations, then checks:
- invalid memory contract values are rejected
- remember writes memory and updates the profile
- duplicate remember merges instead of creating active duplicates
- active event listing hides superseded/forgotten/audit records by default
- revise supersedes the old memory and updates active search/profile results
- revision history can be listed for transparency and user control
- a later thread can retrieve the revised memory
- forget removes the active memory
- forgotten events and forget audit events can be listed explicitly
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import uuid
from pathlib import Path

from dotenv import load_dotenv
from pydantic import ValidationError
from sqlalchemy import text

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.infra.database import dispose_database, get_database, init_database
from app.infra.llm.embedding import init_embedding_model
from app.services.memory import MemoryEvent, get_memory_orchestrator
from scripts.init_database import _init_postgres


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


async def _insert_temp_user_and_threads(user_id: uuid.UUID, threads: list[uuid.UUID]) -> None:
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
            {"user_id": user_id, "display_name": "Memory Verify"},
        )
        for index, thread_id in enumerate(threads, start=1):
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
                    "title": f"Memory Verify {index}",
                },
            )


async def _delete_temp_user(user_id: uuid.UUID) -> None:
    db = get_database()
    async with db.session() as session:
        await session.execute(
            text("DELETE FROM public.users WHERE id = :user_id"),
            {"user_id": user_id},
        )


async def _run_memory_flow() -> None:
    user_id = uuid.uuid4()
    thread_one = uuid.uuid4()
    thread_two = uuid.uuid4()
    orchestrator = get_memory_orchestrator()

    try:
        MemoryEvent(
            user_id=user_id,
            type="unsupported",
            subject="tag",
            value="invalid",
        )
    except ValidationError:
        pass
    else:
        raise AssertionError("invalid memory type should be rejected")

    await _insert_temp_user_and_threads(user_id, [thread_one, thread_two])
    try:
        dislike = await orchestrator.remember_memory(
            MemoryEvent(
                user_id=user_id,
                thread_id=thread_one,
                type="preference",
                subject="tag",
                value="bloody suspense",
                polarity="dislike",
                confidence=0.95,
                source="chat_turn",
            )
        )
        duplicate = await orchestrator.remember_memory(
            MemoryEvent(
                user_id=user_id,
                thread_id=thread_one,
                type="preference",
                subject="tag",
                value="bloody suspense",
                polarity="dislike",
                confidence=0.8,
                source="chat_turn",
            )
        )
        _assert(dislike.id == duplicate.id, "duplicate remember should merge")

        await orchestrator.remember_memory(
            MemoryEvent(
                user_id=user_id,
                thread_id=thread_one,
                type="preference",
                subject="style",
                value="warm character-driven novels",
                polarity="like",
                confidence=0.9,
                source="chat_turn",
            )
        )

        initial = await orchestrator.search_memory(user_id=user_id, limit=20)
        _assert(
            "bloody suspense" in initial.disliked_tags,
            "initial profile should include disliked bloody suspense",
        )
        _assert(
            "warm character-driven novels" in initial.preferred_tags,
            "initial profile should include warm character-driven novels",
        )
        active_list = await orchestrator.list_memory_events(user_id=user_id, limit=20)
        _assert(
            active_list.total == 2,
            "default event list should show two active memories",
        )
        _assert(
            {event.value for event in active_list.events}
            == {"bloody suspense", "warm character-driven novels"},
            "default event list should contain active preference memories",
        )

        revised = await orchestrator.revise_memory(
            user_id=user_id,
            old_value="Suspense is fine, just not bloody or too dark.",
            old_subject="tag",
            old_type="preference",
            new_event=MemoryEvent(
                user_id=user_id,
                thread_id=thread_one,
                type="correction",
                subject="tag",
                value="bloody or too dark suspense",
                polarity="avoid",
                confidence=0.98,
                source="chat_turn",
            ),
        )
        _assert(
            revised.revision_of == dislike.id,
            "fuzzy revise should supersede the old bloody suspense memory",
        )
        active_after_revision = await orchestrator.list_memory_events(
            user_id=user_id,
            query="suspense",
            limit=20,
        )
        active_after_revision_values = {
            event.value for event in active_after_revision.events
        }
        _assert(
            "bloody or too dark suspense" in active_after_revision_values,
            "active event list should include revised memory",
        )
        _assert(
            "bloody suspense" not in active_after_revision_values,
            "active event list should hide superseded memory",
        )
        revision_history = await orchestrator.list_memory_events(
            user_id=user_id,
            query="suspense",
            include_superseded=True,
            limit=20,
        )
        history_by_id = {event.id: event for event in revision_history.events}
        _assert(
            history_by_id[dislike.id].superseded_by == revised.id,
            "superseded event should point to the revised memory",
        )
        _assert(
            history_by_id[revised.id].revision_of == dislike.id,
            "revised memory should point back to the old memory",
        )

        later_thread = await orchestrator.search_memory(
            user_id=user_id,
            thread_id=thread_two,
            query="suspense",
            limit=20,
        )
        active_values = {event.value for event in later_thread.relevant_events}
        _assert(
            "bloody or too dark suspense" in active_values,
            "later thread should retrieve the revised suspense memory",
        )
        _assert(
            "bloody suspense" not in active_values,
            "later thread should not retrieve the superseded memory",
        )

        forget = await orchestrator.forget_memory(
            user_id=user_id,
            memory_id=revised.id,
            thread_id=thread_one,
            reason="verification cleanup",
        )
        _assert(
            forget.forgotten_count == 1,
            "forget should forget one active memory",
        )

        after_forget = await orchestrator.search_memory(
            user_id=user_id,
            query="suspense",
            limit=20,
        )
        _assert(
            all(event.id != revised.id for event in after_forget.relevant_events),
            "forgotten memory should not be active",
        )
        default_after_forget = await orchestrator.list_memory_events(
            user_id=user_id,
            query="suspense",
            limit=20,
        )
        _assert(
            all(event.id != revised.id for event in default_after_forget.events),
            "default event list should hide forgotten memory",
        )
        current_after_forget = await orchestrator.list_current_memories(
            user_id=user_id,
            query="suspense",
            limit=20,
        )
        _assert(
            all(event.id != revised.id for event in current_after_forget.memories),
            "current memory list should hide forgotten memory",
        )
        forgotten_history = await orchestrator.list_memory_events(
            user_id=user_id,
            query="suspense",
            include_forgotten=True,
            include_superseded=True,
            limit=20,
        )
        _assert(
            any(
                event.id == revised.id and event.forgotten
                for event in forgotten_history.events
            ),
            "forgotten history should include the forgotten memory",
        )
        audit_history = await orchestrator.list_memory_events(
            user_id=user_id,
            include_audit=True,
            limit=20,
        )
        _assert(
            any(event.type == "forget" for event in audit_history.events),
            "audit history should include the forget event when requested",
        )

        print("memory flow verification passed")
        print(f"user_id={user_id}")
    finally:
        await _delete_temp_user(user_id)


async def _main(skip_migration: bool) -> None:
    load_dotenv()
    if not skip_migration:
        _init_postgres()
    init_embedding_model()
    await init_database()
    try:
        await _run_memory_flow()
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
