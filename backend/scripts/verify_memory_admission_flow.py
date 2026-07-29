"""
Verify Phase K MemoryAdmission before long-term memory writes.

Usage:
    cd backend
    .\\.venv\\Scripts\\python.exe scripts\\verify_memory_admission_flow.py

This check avoids LLM and network calls. It verifies:
- user-expressed preferences and reading states are admitted
- search results, research evidence, summaries, temporary state, and low-trust
  model inference cannot write memory_events rows
- broad values are rejected
- forgotten memories are not reintroduced without explicit restore metadata
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
            {"user_id": user_id, "display_name": "Memory Admission Verify"},
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
                "title": "Memory Admission Verify",
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
    source_text: str,
) -> dict:
    key_value = "_".join(value.lower().split())[:80] or "fact"
    return {
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
            "raw_text": source_text,
            "state_value": {
                "subject": subject,
                "value": value,
            },
            "relation": {},
            "use_when": ["memory admission verification"],
        },
    }


async def _assert_blocked_without_write(
    candidate: MemoryCandidate,
    *,
    expected_decision: str,
    expected_reason: str,
) -> None:
    orchestrator = get_memory_orchestrator()
    before = await _memory_event_count(candidate.user_id)
    result = await orchestrator.remember_candidate(candidate)
    after = await _memory_event_count(candidate.user_id)
    _assert(
        result.decision.decision == expected_decision,
        f"expected {expected_decision}, got {result.decision.decision}",
    )
    _assert(
        result.decision.reason == expected_reason,
        f"expected reason {expected_reason}, got {result.decision.reason}",
    )
    _assert(result.memory is None, "blocked admission should not return a memory")
    _assert(after == before, "blocked admission should not write memory_events")


async def _run_memory_admission_flow() -> None:
    user_id = uuid.uuid4()
    thread_id = uuid.uuid4()
    orchestrator = get_memory_orchestrator()

    await _insert_temp_user_and_thread(user_id, thread_id)
    try:
        preference = await orchestrator.remember_candidate(
            MemoryCandidate(
                user_id=user_id,
                thread_id=thread_id,
                type="preference",
                subject="style",
                value="warm character-driven novels",
                polarity="like",
                source_kind="user_message",
                source_text="I like warm character-driven novels.",
                confidence=0.95,
                metadata=_precommitted_user_fact(
                    subject="style",
                    value="warm character-driven novels",
                    source_text="I like warm character-driven novels.",
                ),
            )
        )
        _assert(preference.decision.decision == "allow", "preference should be allowed")
        _assert(preference.memory is not None, "allowed preference should be written")

        reading_state = await orchestrator.remember_candidate(
            MemoryCandidate(
                user_id=user_id,
                thread_id=thread_id,
                type="reading_state",
                subject="book",
                value="Nonviolent Communication",
                polarity="read",
                source_kind="book_feedback",
                source_text="I have read Nonviolent Communication.",
                confidence=0.98,
            )
        )
        _assert(
            reading_state.decision.decision == "allow",
            "reading state should be allowed",
        )
        _assert(reading_state.memory is not None, "allowed reading state should write")

        await _assert_blocked_without_write(
            MemoryCandidate(
                user_id=user_id,
                type="preference",
                subject="theme",
                value="top web search result said mindfulness is popular",
                polarity="neutral",
                source_kind="search_result",
            ),
            expected_decision="reject",
            expected_reason="search_result_cannot_enter_long_term_memory",
        )
        await _assert_blocked_without_write(
            MemoryCandidate(
                user_id=user_id,
                type="preference",
                subject="theme",
                value="source claims this topic is well supported",
                polarity="neutral",
                source_kind="research_evidence",
            ),
            expected_decision="reject",
            expected_reason="research_evidence_cannot_enter_long_term_memory",
        )
        await _assert_blocked_without_write(
            MemoryCandidate(
                user_id=user_id,
                type="preference",
                subject="style",
                value="probably enjoys philosophical fiction",
                polarity="like",
                source_kind="model_inference",
            ),
            expected_decision="needs_confirmation",
            expected_reason="model_inference_requires_user_confirmation",
        )
        await _assert_blocked_without_write(
            MemoryCandidate(
                user_id=user_id,
                type="preference",
                subject="user",
                value="temporary turn calculation",
                polarity="neutral",
                scope="temporary_turn_state",
                source_kind="temporary_turn_state",
            ),
            expected_decision="reject",
            expected_reason="non_long_term_scope",
        )
        await _assert_blocked_without_write(
            MemoryCandidate(
                user_id=user_id,
                type="preference",
                subject="style",
                value="这个",
                polarity="like",
                source_kind="user_message",
                metadata=_precommitted_user_fact(
                    subject="style",
                    value="这个",
                    source_text="我喜欢这个",
                ),
            ),
            expected_decision="reject",
            expected_reason="value_too_broad",
        )

        forgotten = await orchestrator.remember_candidate(
            MemoryCandidate(
                user_id=user_id,
                thread_id=thread_id,
                type="preference",
                subject="style",
                value="quiet healing memoirs",
                polarity="like",
                source_kind="user_message",
                source_text="I like quiet healing memoirs.",
                metadata=_precommitted_user_fact(
                    subject="style",
                    value="quiet healing memoirs",
                    source_text="I like quiet healing memoirs.",
                ),
            )
        )
        _assert(forgotten.memory is not None, "setup memory should be written")
        await orchestrator.forget_memory(
            user_id=user_id,
            memory_id=forgotten.memory.id,
            thread_id=thread_id,
            reason="phase k verify forgotten reintroduction",
        )
        await _assert_blocked_without_write(
            MemoryCandidate(
                user_id=user_id,
                thread_id=thread_id,
                type="preference",
                subject="style",
                value="quiet healing memoirs",
                polarity="like",
                source_kind="user_message",
                source_text="Candidate repeats a forgotten memory.",
                metadata=_precommitted_user_fact(
                    subject="style",
                    value="quiet healing memoirs",
                    source_text="Candidate repeats a forgotten memory.",
                ),
            ),
            expected_decision="reject",
            expected_reason="inactive_memory_requires_explicit_restore",
        )

        print("memory admission verification passed")
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
        await _run_memory_admission_flow()
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
