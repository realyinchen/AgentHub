"""Verify deterministic user profile memory capture.

This check avoids LLM calls. It verifies:
- explicit name statements become local long-term user profile memory
- new threads can see the captured profile memory through ContextPack
- profile lookup turns may read memory without enabling memory writes
- changing the profile name revises the previous current name

Usage:
    cd backend
    .\\.venv\\Scripts\\python.exe scripts\\verify_profile_memory_capture_flow.py
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
from app.schemas.chat import UserInput
from app.services.book_intent import build_turn_policy
from app.services.book_turn_orchestration import plan_book_assistant_turn
from app.services.memory.orchestrator import get_memory_orchestrator
from app.services.profile_memory_capture import capture_explicit_profile_memories
from scripts.init_database import _init_postgres


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def _text(*codes: int) -> str:
    return "".join(chr(code) for code in codes)


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
            {"user_id": user_id, "display_name": "Profile Memory Verify"},
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
                "title": "Profile Memory Verify",
            },
        )


async def _delete_temp_user(user_id: uuid.UUID) -> None:
    db = get_database()
    async with db.session() as session:
        await session.execute(
            text("DELETE FROM public.users WHERE id = :user_id"),
            {"user_id": user_id},
        )


async def _run_profile_memory_capture_flow() -> None:
    user_id = uuid.uuid4()
    first_thread_id = uuid.uuid4()
    second_thread_id = uuid.uuid4()
    await _insert_temp_user_and_thread(user_id, first_thread_id)
    await _insert_temp_user_and_thread(user_id, second_thread_id)
    try:
        name_text = _text(25105, 26159, 20912, 38706)
        name_policy = build_turn_policy(name_text)
        _assert(name_policy.can_write_memory is True, str(name_policy))
        _assert("remember_memory" in name_policy.denied_tools, str(name_policy))
        first = await capture_explicit_profile_memories(
            UserInput(
                content=name_text,
                user_id=user_id,
                thread_id=first_thread_id,
                request_id="verify-profile-name",
            )
        )
        _assert(first.captured_count == 1, str(first))
        _assert(
            first.memories[0]["memory"]["value"]
            == _text(110, 97, 109, 101, 58, 32, 20912, 38706),
            str(first.memories[0]),
        )
        _assert(
            first.memories[0]["memory"]["thread_id"] == str(first_thread_id),
            str(first.memories[0]),
        )

        like_text = _text(25105, 21916, 27426, 29483, 21674, 36825, 31181)
        like_capture = await capture_explicit_profile_memories(
            UserInput(
                content=like_text,
                user_id=user_id,
                thread_id=first_thread_id,
                request_id="verify-profile-like",
            )
        )
        _assert(like_capture.captured_count == 1, str(like_capture))
        like_memory = like_capture.memories[0]["memory"]
        _assert(like_memory["subject"] == "tag", str(like_memory))
        _assert(like_memory["value"] == _text(29483, 21674), str(like_memory))
        _assert(like_memory["polarity"] == "like", str(like_memory))

        lookup_text = _text(25105, 21483, 20160, 20040, 21517, 23383)
        lookup_capture = await capture_explicit_profile_memories(
            UserInput(
                content=lookup_text,
                user_id=user_id,
                thread_id=first_thread_id,
                request_id="verify-profile-lookup-no-capture",
            )
        )
        _assert(lookup_capture.captured_count == 0, str(lookup_capture))

        policy = build_turn_policy(lookup_text)
        _assert(policy.can_search_memory is True, str(policy))
        _assert(policy.can_write_memory is False, str(policy))
        _assert("search_memory" in policy.allowed_tools, str(policy.allowed_tools))
        _assert("remember_memory" in policy.denied_tools, str(policy.denied_tools))

        plan = await plan_book_assistant_turn(
            None,
            user_id=user_id,
            user_message=lookup_text,
            query=lookup_text,
        )
        _assert(plan.route == "answer_question", str(plan))
        _assert(plan.recommended_next_tools == ["search_memory"], str(plan))

        visible = await get_memory_orchestrator().list_current_memories(
            user_id=user_id,
            limit=20,
        )
        active_values = [memory.value for memory in visible.memories]
        _assert(
            _text(110, 97, 109, 101, 58, 32, 20912, 38706) in active_values,
            str(active_values),
        )

        rename_text = _text(25105, 21483, 38738, 31481)
        second = await capture_explicit_profile_memories(
            UserInput(
                content=rename_text,
                user_id=user_id,
                thread_id=second_thread_id,
                request_id="verify-profile-rename",
            )
        )
        _assert(second.captured_count == 1, str(second))

        current = await get_memory_orchestrator().list_current_memories(
            user_id=user_id,
            limit=20,
        )
        name_values = [
            memory.value
            for memory in current.memories
            if memory.subject == "user" and memory.value.lower().startswith("name:")
        ]
        _assert(
            name_values == [_text(110, 97, 109, 101, 58, 32, 38738, 31481)],
            str(name_values),
        )

        print("profile memory capture verification passed")
        print(f"user_id={user_id}")
        print(f"first_thread_id={first_thread_id}")
        print(f"second_thread_id={second_thread_id}")
    finally:
        await _delete_temp_user(user_id)


async def _main(skip_migration: bool) -> None:
    load_dotenv()
    if not skip_migration:
        _init_postgres()
    init_embedding_model()
    await init_database()
    try:
        await _run_profile_memory_capture_flow()
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
