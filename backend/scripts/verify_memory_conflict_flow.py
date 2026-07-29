"""
Verify Phase L MemoryConflictResolver before long-term memory writes.

Usage:
    cd backend
    .\\.venv\\Scripts\\python.exe scripts\\verify_memory_conflict_flow.py

This check avoids LLM and network calls. It verifies:
- duplicate memories do not create new memory_events rows
- direct polarity conflicts revise the current memory
- explicit broad-to-specific corrections revise the broad memory
- want -> read book state is treated as state progression
- ambiguous correction targets return needs_confirmation and do not write
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import uuid
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import text

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.infra.database import dispose_database, get_database, init_database
from app.infra.llm.embedding import init_embedding_model
from app.services.memory import MemoryCandidate, get_memory_orchestrator
from scripts.init_database import _init_postgres


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


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
            {"user_id": user_id, "display_name": "Memory Conflict Verify"},
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
                "title": "Memory Conflict Verify",
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


def _precommitted_user_fact(
    *,
    subject: str,
    value: str,
    source_text: str = "",
    extra: dict | None = None,
) -> dict:
    key_value = "_".join(value.lower().split())[:80] or "fact"
    metadata = {
        "precommit": {
            "source_identified": True,
            "reference_resolved": True,
            "completeness_validated": True,
            "persistence_approved": True,
        },
        "user_state": {
            "status": "active",
            "category": "preference",
            "state_key": f"preference.{subject}.{key_value}",
            "summary": value,
            "raw_text": source_text or value,
            "state_value": {
                "subject": subject,
                "value": value,
            },
            "relation": {},
            "use_when": ["memory conflict verification"],
        },
    }
    metadata.update(extra or {})
    return metadata


async def _run_memory_conflict_flow() -> None:
    user_id = uuid.uuid4()
    thread_id = uuid.uuid4()
    orchestrator = get_memory_orchestrator()

    await _insert_temp_user_and_thread(user_id, thread_id)
    try:
        duplicate_first = await orchestrator.remember_candidate(
            MemoryCandidate(
                user_id=user_id,
                thread_id=thread_id,
                type="preference",
                subject="style",
                value="quiet lyrical fiction",
                polarity="like",
                source_kind="user_message",
                source_text="I like quiet lyrical fiction.",
                metadata=_precommitted_user_fact(
                    subject="style",
                    value="quiet lyrical fiction",
                    source_text="I like quiet lyrical fiction.",
                ),
            )
        )
        _assert(duplicate_first.memory is not None, "setup duplicate memory should write")
        count_before_duplicate = await _memory_event_count(user_id)
        duplicate_second = await orchestrator.remember_candidate(
            MemoryCandidate(
                user_id=user_id,
                thread_id=thread_id,
                type="preference",
                subject="style",
                value="quiet lyrical fiction",
                polarity="like",
                source_kind="user_message",
                source_text="I still like quiet lyrical fiction.",
                metadata=_precommitted_user_fact(
                    subject="style",
                    value="quiet lyrical fiction",
                    source_text="I still like quiet lyrical fiction.",
                ),
            )
        )
        _assert(
            duplicate_second.memory is not None
            and duplicate_second.memory.id == duplicate_first.memory.id,
            "duplicate should return existing memory",
        )
        _assert(
            duplicate_second.conflicts
            and duplicate_second.conflicts[0].conflict_type == "duplicate",
            "duplicate conflict should be structured",
        )
        _assert(
            await _memory_event_count(user_id) == count_before_duplicate,
            "duplicate should not create a memory_events row",
        )

        liked = await orchestrator.remember_candidate(
            MemoryCandidate(
                user_id=user_id,
                thread_id=thread_id,
                type="preference",
                subject="style",
                value="slow literary fiction",
                polarity="like",
                source_kind="user_message",
                metadata=_precommitted_user_fact(
                    subject="style",
                    value="slow literary fiction",
                ),
            )
        )
        disliked = await orchestrator.remember_candidate(
            MemoryCandidate(
                user_id=user_id,
                thread_id=thread_id,
                type="preference",
                subject="style",
                value="slow literary fiction",
                polarity="dislike",
                source_kind="user_message",
                metadata=_precommitted_user_fact(
                    subject="style",
                    value="slow literary fiction",
                ),
            )
        )
        _assert(liked.memory is not None, "setup polarity memory should write")
        _assert(disliked.memory is not None, "polarity revision should write")
        _assert(
            disliked.memory.revision_of == liked.memory.id,
            "direct polarity conflict should revise existing memory",
        )
        _assert(
            disliked.conflicts
            and disliked.conflicts[0].conflict_type == "direct_polarity_conflict",
            "direct polarity conflict should be structured",
        )

        broad = await orchestrator.remember_candidate(
            MemoryCandidate(
                user_id=user_id,
                thread_id=thread_id,
                type="preference",
                subject="content",
                value="suspense",
                polarity="avoid",
                source_kind="user_message",
                source_text="I avoid suspense.",
                metadata=_precommitted_user_fact(
                    subject="content",
                    value="suspense",
                    source_text="I avoid suspense.",
                ),
            )
        )
        refined = await orchestrator.remember_candidate(
            MemoryCandidate(
                user_id=user_id,
                thread_id=thread_id,
                type="preference",
                subject="content",
                value="bloody or too dark suspense",
                polarity="avoid",
                source_kind="user_message",
                source_text="Suspense is fine, just not bloody or too dark.",
                metadata=_precommitted_user_fact(
                    subject="content",
                    value="bloody or too dark suspense",
                    source_text=(
                        "Suspense is fine, just not bloody or too dark."
                    ),
                    extra={"explicit_correction": True},
                ),
            )
        )
        _assert(broad.memory is not None, "setup broad preference should write")
        _assert(refined.memory is not None, "refinement should write")
        _assert(
            refined.memory.revision_of == broad.memory.id,
            "explicit refinement should revise broad preference",
        )
        _assert(
            refined.conflicts
            and refined.conflicts[0].conflict_type
            in {"preference_refinement", "explicit_correction"},
            "refinement should be structured",
        )

        want = await orchestrator.remember_candidate(
            MemoryCandidate(
                user_id=user_id,
                thread_id=thread_id,
                type="reading_state",
                subject="book",
                value="Nonviolent Communication",
                polarity="want",
                source_kind="book_feedback",
            )
        )
        read = await orchestrator.remember_candidate(
            MemoryCandidate(
                user_id=user_id,
                thread_id=thread_id,
                type="reading_state",
                subject="book",
                value="Nonviolent Communication",
                polarity="read",
                source_kind="book_feedback",
                source_text="I finished Nonviolent Communication.",
            )
        )
        _assert(want.memory is not None, "setup want state should write")
        _assert(read.memory is not None, "read state should write")
        _assert(
            read.memory.revision_of == want.memory.id,
            "want -> read should revise reading state",
        )
        _assert(
            read.conflicts
            and read.conflicts[0].conflict_type == "state_progression",
            "state progression should be structured",
        )

        await orchestrator.remember_candidate(
            MemoryCandidate(
                user_id=user_id,
                thread_id=thread_id,
                type="preference",
                subject="style",
                value="quiet memoirs",
                polarity="like",
                source_kind="user_message",
                metadata=_precommitted_user_fact(
                    subject="style",
                    value="quiet memoirs",
                ),
            )
        )
        await orchestrator.remember_candidate(
            MemoryCandidate(
                user_id=user_id,
                thread_id=thread_id,
                type="preference",
                subject="style",
                value="quiet family sagas",
                polarity="like",
                source_kind="user_message",
                metadata=_precommitted_user_fact(
                    subject="style",
                    value="quiet family sagas",
                ),
            )
        )
        count_before_ambiguous = await _memory_event_count(user_id)
        ambiguous = await orchestrator.remember_candidate(
            MemoryCandidate(
                user_id=user_id,
                thread_id=thread_id,
                type="correction",
                subject="style",
                value="quiet healing novels",
                polarity="like",
                source_kind="user_message",
                source_text="Actually I meant quiet healing novels.",
                metadata=_precommitted_user_fact(
                    subject="style",
                    value="quiet healing novels",
                    source_text="Actually I meant quiet healing novels.",
                    extra={"explicit_correction": True},
                ),
            )
        )
        _assert(
            ambiguous.decision.decision == "needs_confirmation",
            "ambiguous correction should need confirmation",
        )
        _assert(ambiguous.memory is None, "ambiguous correction should not write")
        _assert(
            await _memory_event_count(user_id) == count_before_ambiguous,
            "ambiguous correction should not create a memory_events row",
        )

        current = await orchestrator.list_current_memories(user_id=user_id, limit=100)
        current_by_id = {event.id: event for event in current.memories}
        _assert(
            broad.memory.id not in current_by_id,
            "broad superseded preference should no longer be current",
        )
        _assert(
            want.memory.id not in current_by_id,
            "want state should no longer be current after read progression",
        )

        print("memory conflict verification passed")
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
        await _run_memory_conflict_flow()
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
