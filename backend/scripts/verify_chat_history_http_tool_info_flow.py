"""Verify chat history HTTP route preserves route-first tool_info.

This is a local ASGI-level acceptance check. It uses the real FastAPI route,
query parsing, dependency injection, and database ownership check, but avoids
uvicorn, LLM/provider calls, mem0, and gbrain.
"""

from __future__ import annotations

import argparse
import asyncio
import importlib
import json
import sys
import uuid
from pathlib import Path

import httpx
from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.infra.database import dispose_database, init_database
from scripts.init_database import _init_postgres
from scripts.verify_chat_history_api_tool_info_flow import (
    _FakeAgent,
    _delete_temp_user,
    _insert_temp_user_and_thread,
)
from scripts.verify_chat_route_panel_flow import _messages


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


async def _verify_http_history_route() -> None:
    owner_id = uuid.uuid4()
    stranger_id = uuid.uuid4()
    thread_id = uuid.uuid4()
    fake_agent = _FakeAgent(_messages())

    history_api = importlib.import_module("app.api.v1.chat.history")
    original_get_agent = history_api.get_agent
    history_api.get_agent = lambda: fake_agent

    try:
        await _insert_temp_user_and_thread(owner_id, thread_id)

        # Import after database setup/monkeypatch preparation. The app lifespan
        # is intentionally not run by ASGITransport; this verifier owns setup.
        from app.main import app

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://testserver",
        ) as client:
            owner_response = await client.get(
                f"/api/v1/chat/history/{thread_id}",
                params={"user_id": str(owner_id)},
            )
            stranger_response = await client.get(
                f"/api/v1/chat/history/{thread_id}",
                params={"user_id": str(stranger_id)},
            )

        _assert(owner_response.status_code == 200, owner_response.text)
        _assert(stranger_response.status_code == 200, stranger_response.text)

        owner_payload = owner_response.json()
        stranger_payload = stranger_response.json()
        _assert(stranger_payload == {"messages": [], "message_sequence": []}, str(stranger_payload))

        messages = owner_payload.get("messages")
        _assert(isinstance(messages, list), str(owner_payload))
        _assert(len(messages) == 2, str(owner_payload))
        _assert(messages[0]["type"] == "human", str(messages[0]))
        final_message = messages[1]
        _assert(final_message["type"] == "ai", str(final_message))
        _assert(
            "already in your reading history" in final_message["content"],
            str(final_message),
        )

        tool_info = final_message.get("custom_data", {}).get("tool_info")
        _assert(isinstance(tool_info, list), str(final_message))
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
        _assert(history_payload["result_mode"] == "recommendation_history", str(history_payload))
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
        _assert(fake_agent.seen_thread_ids == [str(thread_id)], str(fake_agent.seen_thread_ids))
    finally:
        history_api.get_agent = original_get_agent
        await _delete_temp_user(owner_id)


async def _main(skip_migration: bool) -> None:
    load_dotenv(BACKEND_DIR / ".env")
    if not skip_migration:
        _init_postgres()
    await init_database()
    try:
        await _verify_http_history_route()
    finally:
        await dispose_database()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-migration", action="store_true")
    args = parser.parse_args()

    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(_main(skip_migration=args.skip_migration))
    print("chat history HTTP tool_info verification passed")


if __name__ == "__main__":
    main()
