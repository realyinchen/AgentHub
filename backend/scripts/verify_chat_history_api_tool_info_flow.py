"""Verify chat history API preserves route-first tool_info for persisted UI.

This is an API-level acceptance check for the visible flowchart path. It avoids
LLM/provider calls by replacing the agent with a fake checkpointer state, while
still exercising the real chat history endpoint function and conversation
ownership check.

It verifies:
- final AI chat history messages receive ordered custom_data.tool_info
- book-turn-orchestration-v1 and recommendation_history payloads survive API
  projection
- suppressed_records stay available for frontend history/explanation panels
- a different user cannot read the thread history
"""

from __future__ import annotations

import argparse
import asyncio
import importlib
import json
import sys
import uuid
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from dotenv import load_dotenv
from sqlalchemy import text

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.infra.database import dispose_database, get_database, init_database
from scripts.init_database import _init_postgres
from scripts.verify_chat_route_panel_flow import _messages


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


class _FakeAgent:
    def __init__(self, messages: list[Any]) -> None:
        self.messages = messages
        self.seen_thread_ids: list[str] = []

    async def aget_state(self, *, config: Any) -> SimpleNamespace:
        configurable = dict(config.get("configurable", {}))
        self.seen_thread_ids.append(str(configurable.get("thread_id", "")))
        return SimpleNamespace(values={"messages": self.messages})


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
            {"user_id": user_id, "display_name": "Chat History API Verify"},
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
                "title": "Chat History API Verify",
            },
        )


async def _delete_temp_user(user_id: uuid.UUID) -> None:
    db = get_database()
    async with db.session() as session:
        await session.execute(
            text("DELETE FROM public.users WHERE id = :user_id"),
            {"user_id": user_id},
        )


async def _verify_history_api_projection() -> None:
    owner_id = uuid.uuid4()
    stranger_id = uuid.uuid4()
    thread_id = uuid.uuid4()
    fake_agent = _FakeAgent(_messages())

    history_api = importlib.import_module("app.api.v1.chat.history")
    original_get_agent = history_api.get_agent
    history_api.get_agent = lambda: fake_agent

    try:
        await _insert_temp_user_and_thread(owner_id, thread_id)

        db = get_database()
        async with db.session() as session:
            owner_history = await history_api.history(
                thread_id,
                user_id=owner_id,
                db=session,
            )
            stranger_history = await history_api.history(
                thread_id,
                user_id=stranger_id,
                db=session,
            )

        _assert(fake_agent.seen_thread_ids == [str(thread_id)], str(fake_agent.seen_thread_ids))
        _assert(stranger_history.messages == [], str(stranger_history))
        _assert(stranger_history.message_sequence == [], str(stranger_history))

        _assert(len(owner_history.messages) == 2, str(owner_history.messages))
        human_message, final_message = owner_history.messages
        _assert(human_message.type == "human", human_message.model_dump_json())
        _assert(final_message.type == "ai", final_message.model_dump_json())
        _assert("already in your reading history" in final_message.content, final_message.content)

        tool_info = final_message.custom_data.get("tool_info")
        _assert(isinstance(tool_info, list), str(final_message.custom_data))
        _assert(len(tool_info) == 2, str(tool_info))
        _assert([item["order"] for item in tool_info] == [0, 1], str(tool_info))
        _assert(
            [item["name"] for item in tool_info]
            == ["plan_book_assistant_turn", "get_recommendation_history"],
            str(tool_info),
        )

        route_payload = json.loads(tool_info[0]["output"])
        history_payload = json.loads(tool_info[1]["output"])
        _assert(
            route_payload["contract_version"] == "book-turn-orchestration-v1",
            str(route_payload),
        )
        _assert(route_payload["route"] == "recommendation_history", str(route_payload))
        _assert("search_books" in route_payload["denied_tools"], str(route_payload))
        _assert(
            history_payload["result_mode"] == "recommendation_history",
            str(history_payload),
        )
        _assert(history_payload["records"] == [], str(history_payload))
        _assert(history_payload["suppressed_records"], str(history_payload))
        _assert(
            history_payload["suppressed_records"][0]["book_title"] == "Dune",
            str(history_payload),
        )
        _assert(
            history_payload["metadata"]["suppressed_records_are_history_only"] is True,
            str(history_payload),
        )
    finally:
        history_api.get_agent = original_get_agent
        await _delete_temp_user(owner_id)


async def _main(skip_migration: bool) -> None:
    load_dotenv(BACKEND_DIR / ".env")
    if not skip_migration:
        _init_postgres()
    await init_database()
    try:
        await _verify_history_api_projection()
    finally:
        await dispose_database()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-migration", action="store_true")
    args = parser.parse_args()

    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(_main(skip_migration=args.skip_migration))
    print("chat history API tool_info verification passed")


if __name__ == "__main__":
    main()
