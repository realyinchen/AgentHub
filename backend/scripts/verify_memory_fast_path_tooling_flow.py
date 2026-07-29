r"""Verify fast user-state persistence, pet recall, and visible tool steps."""

from __future__ import annotations

import asyncio
import json
import sys
import uuid
from pathlib import Path

import httpx
from dotenv import load_dotenv
from sqlalchemy import text


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.infra.database import dispose_database, get_database, init_database
from app.infra.llm.embedding import init_embedding_model


BASE_URL = "http://127.0.0.1:8080/api/v1"


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


async def _seed_user(user_id: uuid.UUID) -> None:
    database = get_database()
    async with database.session() as session:
        await session.execute(
            text(
                """
                INSERT INTO public.users (id, display_name, is_mock_user)
                VALUES (:user_id, :display_name, true)
                ON CONFLICT (id) DO NOTHING
                """
            ),
            {"user_id": user_id, "display_name": "Fast Memory Tool Verify"},
        )


async def _cleanup(user_id: uuid.UUID) -> None:
    database = get_database()
    async with database.session() as session:
        await session.execute(
            text("DELETE FROM public.users WHERE id = :user_id"),
            {"user_id": user_id},
        )


async def _stream_turn(
    client: httpx.AsyncClient,
    *,
    content: str,
    user_id: uuid.UUID,
    thread_id: uuid.UUID,
    request_id: str,
) -> list[dict]:
    events: list[dict] = []
    async with client.stream(
        "POST",
        "/chat/stream",
        json={
            "content": content,
            "user_id": str(user_id),
            "thread_id": str(thread_id),
            "request_id": request_id,
        },
    ) as response:
        if response.status_code != 200:
            raise AssertionError((await response.aread()).decode(errors="replace"))
        async for line in response.aiter_lines():
            if not line.startswith("data: "):
                continue
            payload = line[6:].strip()
            if not payload or payload == "[DONE]":
                continue
            events.append(json.loads(payload))
    return events


def _final_message(events: list[dict]) -> dict:
    messages = [event.get("content") for event in events if event.get("type") == "message"]
    _assert(bool(messages), str(events))
    return messages[-1]


async def _wait_for_history_tool(
    client: httpx.AsyncClient,
    *,
    user_id: uuid.UUID,
    thread_id: uuid.UUID,
    tool_name: str,
) -> dict:
    last_payload: dict = {}
    for _ in range(30):
        response = await client.get(
            f"/chat/history/{thread_id}",
            params={"user_id": str(user_id)},
        )
        _assert(response.status_code == 200, response.text)
        last_payload = response.json()
        has_tool_step = any(
            step.get("message_type") == "tool"
            for step in last_payload.get("message_sequence") or []
        )
        for message in last_payload.get("messages") or []:
            tool_info = (message.get("custom_data") or {}).get("tool_info") or []
            if has_tool_step and any(item.get("name") == tool_name for item in tool_info):
                return last_payload
        await asyncio.sleep(0.1)
    raise AssertionError(f"history did not persist {tool_name}: {last_payload}")


async def _run() -> None:
    user_id = uuid.uuid4()
    write_thread = uuid.uuid4()
    recall_thread = uuid.uuid4()
    await _seed_user(user_id)
    try:
        async with httpx.AsyncClient(base_url=BASE_URL, timeout=20) as client:
            cat_events = await _stream_turn(
                client,
                content=(
                    "\u6211\u6709\u4e00\u53ea\u732b\u54aa\u53eb\u54aa\u54aa\uff0c"
                    "\u662f\u4e00\u53ea\u4e09\u82b1\u6bcd\u732b"
                ),
                user_id=user_id,
                thread_id=write_thread,
                request_id="fast-memory-cat",
            )
            dog_events = await _stream_turn(
                client,
                content=(
                    "\u6211\u8fd8\u6709\u4e00\u53ea\u53eb\u65fa\u8d22\u7684\u72d7\uff0c"
                    "\u662f\u4e00\u53ea\u9ec4\u8272\u519c\u6751\u571f\u72d7"
                ),
                user_id=user_id,
                thread_id=write_thread,
                request_id="fast-memory-dog",
            )
            for events in (cat_events, dog_events):
                _assert(
                    any(
                        event.get("type") == "tool"
                        and (event.get("content") or {}).get("name")
                        == "process_memory_write_request"
                        for event in events
                    ),
                    str(events),
                )
                message = _final_message(events)
                tool_info = (message.get("custom_data") or {}).get("tool_info") or []
                _assert(
                    any(
                        item.get("name") == "process_memory_write_request"
                        for item in tool_info
                    ),
                    str(message),
                )
                _assert("\u6743\u9650\u9650\u5236" not in str(message.get("content") or ""), str(message))

            recall_events = await _stream_turn(
                client,
                content="\u6211\u6709\u51e0\u53ea\u5ba0\u7269",
                user_id=user_id,
                thread_id=recall_thread,
                request_id="fast-memory-pet-count",
            )
            _assert(
                any(
                    event.get("type") == "tool"
                    and (event.get("content") or {}).get("name") == "search_memory"
                    for event in recall_events
                ),
                str(recall_events),
            )
            recall_message = _final_message(recall_events)
            content = str(recall_message.get("content") or "")
            _assert("2\u53ea\u5ba0\u7269" in content, content)
            _assert("\u54aa\u54aa" in content and "\u65fa\u8d22" in content, content)

            history = await _wait_for_history_tool(
                client,
                user_id=user_id,
                thread_id=recall_thread,
                tool_name="search_memory",
            )
            step_types = [step.get("message_type") for step in history.get("message_sequence") or []]
            _assert("tool" in step_types, str(history))

            current = await client.get(f"/memory/{user_id}/current")
            _assert(current.status_code == 200, current.text)
            names = {
                (item.get("state_value") or {}).get("name")
                for item in current.json().get("memories") or []
            }
            _assert({"\u54aa\u54aa", "\u65fa\u8d22"}.issubset(names), str(names))

            print("fast memory tooling verification passed")
            print(f"recall={content}")
            print(f"history_step_types={step_types}")
    finally:
        await asyncio.sleep(0.5)
        await _cleanup(user_id)


async def _main() -> None:
    load_dotenv()
    init_embedding_model()
    await init_database()
    try:
        await _run()
    finally:
        await dispose_database()


if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(_main())
