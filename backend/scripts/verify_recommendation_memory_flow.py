"""
Verify the personal recommendation memory loop end to end.

This Phase C check intentionally avoids live LLM calls and external book search.
It verifies the app-owned memory contract and the recommendation-ready context
that the agent will read through memory tools.

Usage:
    cd backend
    .\\.venv\\Scripts\\python.exe scripts\\verify_recommendation_memory_flow.py
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

from app.agents.tools import memory as memory_tools
from app.infra.database import dispose_database, get_database, init_database
from app.infra.llm.embedding import init_embedding_model
from app.services.memory import get_memory_orchestrator
from scripts.init_database import _init_postgres


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def _values(events: list[dict[str, Any]]) -> set[str]:
    return {str(event.get("value", "")) for event in events}


def _ids(events: list[dict[str, Any]]) -> set[str]:
    return {str(event.get("id", "")) for event in events if event.get("id")}


async def _insert_temp_user_and_threads(
    user_id: uuid.UUID,
    threads: list[uuid.UUID],
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
            {"user_id": user_id, "display_name": "Recommendation Memory Verify"},
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
                    "title": f"Recommendation Memory Verify {index}",
                },
            )


async def _delete_temp_user(user_id: uuid.UUID) -> None:
    db = get_database()
    async with db.session() as session:
        await session.execute(
            text("DELETE FROM public.users WHERE id = :user_id"),
            {"user_id": user_id},
        )


async def _remember(**payload: Any) -> dict[str, Any]:
    return json.loads(await memory_tools.remember_memory.ainvoke(payload))


async def _revise(**payload: Any) -> dict[str, Any]:
    return json.loads(await memory_tools.revise_memory.ainvoke(payload))


async def _forget(**payload: Any) -> dict[str, Any]:
    return json.loads(await memory_tools.forget_memory.ainvoke(payload))


async def _search(**payload: Any) -> dict[str, Any]:
    return json.loads(await memory_tools.search_memory.ainvoke(payload))


async def _run_recommendation_memory_flow() -> None:
    user_id = uuid.uuid4()
    thread_one = uuid.uuid4()
    thread_two = uuid.uuid4()
    orchestrator = get_memory_orchestrator()

    await _insert_temp_user_and_threads(user_id, [thread_one, thread_two])
    try:
        # User turn 1:
        # "I do not like bloody suspense. Recommend warm character-driven novels."
        avoid_bloody = await _remember(
            user_id=str(user_id),
            thread_id=str(thread_one),
            type="preference",
            subject="content",
            value="bloody suspense",
            polarity="avoid",
            confidence=0.95,
            source="chat_turn",
            metadata={
                "origin": "phase_c",
                "user_feedback": "I do not like bloody suspense.",
            },
        )
        like_warm = await _remember(
            user_id=str(user_id),
            thread_id=str(thread_one),
            type="preference",
            subject="style",
            value="warm character-driven novels",
            polarity="like",
            confidence=0.95,
            source="chat_turn",
            metadata={
                "origin": "phase_c",
                "user_feedback": "Recommend warm character-driven novels.",
            },
        )

        same_turn_memory = await _search(
            user_id=str(user_id),
            thread_id=str(thread_one),
            query="recommend warm character-driven novels without bloody suspense",
            limit=20,
        )
        same_turn_values = _values(same_turn_memory["relevant_events"])
        _assert(
            "bloody suspense" in same_turn_memory["disliked_tags"],
            "same turn profile should include the avoid constraint",
        )
        _assert(
            "warm character-driven novels" in same_turn_memory["preferred_tags"],
            "same turn profile should include the positive style preference",
        )
        _assert(
            {"bloody suspense", "warm character-driven novels"} <= same_turn_values,
            "same turn memory search should retrieve both newly written memories",
        )

        # User turn 2:
        # "Suspense is fine, just not bloody or too dark."
        revised = await _revise(
            user_id=str(user_id),
            memory_id=avoid_bloody["id"],
            old_value="bloody suspense",
            old_subject="content",
            old_type="preference",
            new_type="correction",
            new_subject="content",
            new_value="bloody or too dark suspense",
            new_polarity="avoid",
            confidence=0.98,
            thread_id=str(thread_one),
            source="chat_turn",
            metadata={
                "origin": "phase_c",
                "correction": "Suspense is fine, just not bloody or too dark.",
            },
        )
        _assert(
            revised["revision_of"] == avoid_bloody["id"],
            "correction should revise the old avoid memory",
        )

        after_revision = await _search(
            user_id=str(user_id),
            thread_id=str(thread_one),
            query="suspense",
            limit=20,
        )
        after_revision_ids = _ids(after_revision["relevant_events"])
        _assert(
            revised["id"] in after_revision_ids,
            "revised memory should be active after correction",
        )
        _assert(
            avoid_bloody["id"] not in after_revision_ids,
            "superseded memory should not be active after correction",
        )
        _assert(
            "bloody or too dark suspense" in after_revision["disliked_tags"],
            "profile should use the revised avoid constraint",
        )
        _assert(
            "bloody suspense" not in after_revision["disliked_tags"],
            "profile should remove the superseded avoid constraint",
        )
        _assert(
            "suspense" not in {item.lower() for item in after_revision["disliked_tags"]},
            "correction must not become a broad dislike of suspense",
        )

        current_after_revision = await orchestrator.list_current_memories(
            user_id=user_id,
            query="suspense",
            limit=20,
        )
        current_ids = {str(event.id) for event in current_after_revision.memories}
        _assert(
            revised["id"] in current_ids,
            "current memory list should show the revised memory",
        )
        _assert(
            avoid_bloody["id"] not in current_ids,
            "current memory list should hide the superseded memory",
        )

        # Later/new thread should retrieve only the current revised memory.
        later_thread_memory = await _search(
            user_id=str(user_id),
            thread_id=str(thread_two),
            query="warm suspense recommendation",
            limit=20,
        )
        later_values = _values(later_thread_memory["relevant_events"])
        later_ids = _ids(later_thread_memory["relevant_events"])
        _assert(
            "warm character-driven novels" in later_values,
            "later thread should retrieve the positive style memory",
        )
        _assert(
            revised["id"] in later_ids,
            "later thread should retrieve the revised suspense constraint",
        )
        _assert(
            avoid_bloody["id"] not in later_ids,
            "later thread should not retrieve superseded memory",
        )

        # User forgets the revised suspense constraint.
        forget_result = await _forget(
            user_id=str(user_id),
            memory_id=revised["id"],
            thread_id=str(thread_one),
            reason="phase c user asked to forget suspense content constraint",
        )
        _assert(
            forget_result["forgotten_count"] == 1,
            "forget should mark exactly one current memory as forgotten",
        )

        after_forget = await _search(
            user_id=str(user_id),
            thread_id=str(thread_two),
            query="suspense recommendation",
            limit=20,
        )
        after_forget_ids = _ids(after_forget["relevant_events"])
        after_forget_values = _values(after_forget["relevant_events"])
        _assert(
            revised["id"] not in after_forget_ids,
            "forgotten memory should not be returned to later recommendations",
        )
        _assert(
            "bloody or too dark suspense" not in after_forget["disliked_tags"],
            "forgotten memory should not remain in profile disliked tags",
        )
        _assert(
            "bloody or too dark suspense" not in after_forget_values,
            "forgotten memory should not remain in relevant events",
        )
        _assert(
            "warm character-driven novels" in after_forget["preferred_tags"],
            "forgetting one avoid memory should not remove unrelated preferences",
        )

        current_after_forget = await orchestrator.list_current_memories(
            user_id=user_id,
            query="suspense",
            limit=20,
        )
        _assert(
            all(str(event.id) != revised["id"] for event in current_after_forget.memories),
            "current memory list should hide forgotten memory",
        )

        history = await orchestrator.list_memory_events(
            user_id=user_id,
            query="suspense",
            include_forgotten=True,
            include_superseded=True,
            include_audit=True,
            limit=50,
        )
        history_by_id = {str(event.id): event for event in history.events}
        _assert(
            history_by_id[avoid_bloody["id"]].superseded_by is not None,
            "history should preserve superseded old memory",
        )
        _assert(
            history_by_id[revised["id"]].forgotten,
            "history should preserve the forgotten revised memory",
        )
        _assert(
            any(event.type == "forget" for event in history.events),
            "history should include a forget audit event when requested",
        )

        print("recommendation memory flow verification passed")
        print(f"user_id={user_id}")
        print(f"thread_one={thread_one}")
        print(f"thread_two={thread_two}")
        print(f"warm_memory_id={like_warm['id']}")
        print(f"forgotten_memory_id={revised['id']}")
    finally:
        await _delete_temp_user(user_id)


async def _main(skip_migration: bool) -> None:
    load_dotenv()
    if not skip_migration:
        _init_postgres()
    init_embedding_model()
    await init_database()
    try:
        await _run_recommendation_memory_flow()
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
