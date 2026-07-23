r"""Verify ActionPlan memory write/recall against a running backend."""

from __future__ import annotations

import asyncio
import sys
import time
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
            {"user_id": user_id, "display_name": "Runtime HTTP Verify"},
        )


async def _cleanup(user_id: uuid.UUID) -> None:
    db = get_database()
    async with db.session() as session:
        await session.execute(
            text("DELETE FROM public.users WHERE id = :user_id"),
            {"user_id": user_id},
        )


async def _run() -> None:
    user_id = uuid.uuid4()
    write_thread = uuid.uuid4()
    recall_thread = uuid.uuid4()
    statement = "\u6211\u6709\u4e00\u8f86\u94f6\u8272\u7535\u52a8\u8f66\uff0c\u540d\u5b57\u53eb\u5c0f\u94f6"
    question = "\u6211\u7684\u7535\u52a8\u8f66\u662f\u4ec0\u4e48\uff1f"
    await _seed_user(user_id)
    try:
        async with httpx.AsyncClient(base_url=BASE_URL, timeout=20) as client:
            started = time.perf_counter()
            write_response = await client.post(
                "/chat/invoke",
                json={
                    "content": statement,
                    "user_id": str(user_id),
                    "thread_id": str(write_thread),
                    "request_id": f"http-write-{uuid.uuid4()}",
                },
            )
            write_ms = int((time.perf_counter() - started) * 1000)
            _assert(write_response.status_code == 200, write_response.text)
            write_payload = write_response.json()
            custom = write_payload.get("custom_data") or {}
            trace = custom.get("runtime_trace") or {}
            _assert(trace.get("fast_path") is True, str(write_payload))
            _assert(trace.get("intent") == "memory_write", str(trace))
            tool_info = custom.get("tool_info") or []
            _assert(
                [item.get("name") for item in tool_info] == ["capture_user_state"],
                str(tool_info),
            )
            receipt = custom.get("plan_receipt") or {}
            _assert(receipt.get("status") == "completed", str(receipt))
            _assert("\u5df2\u4fdd\u5b58" in str(write_payload.get("content") or ""), str(write_payload))
            _assert(write_ms < 5000, f"write took {write_ms}ms")

            current_response = await client.get(f"/memory/{user_id}/current")
            _assert(current_response.status_code == 200, current_response.text)
            memories = current_response.json().get("memories") or []
            matching = [
                item
                for item in memories
                if "\u94f6\u8272\u7535\u52a8\u8f66"
                in str(item.get("raw_text") or item.get("value") or "")
            ]
            _assert(matching, str(memories))

            started = time.perf_counter()
            recall_response = await client.post(
                "/chat/invoke",
                json={
                    "content": question,
                    "user_id": str(user_id),
                    "thread_id": str(recall_thread),
                    "request_id": f"http-recall-{uuid.uuid4()}",
                },
            )
            recall_ms = int((time.perf_counter() - started) * 1000)
            _assert(recall_response.status_code == 200, recall_response.text)
            recall_payload = recall_response.json()
            recall_custom = recall_payload.get("custom_data") or {}
            recall_tools = recall_custom.get("tool_info") or []
            _assert(
                [item.get("name") for item in recall_tools] == ["search_memory"],
                str(recall_tools),
            )
            _assert(recall_tools[0].get("system_executed") is True, str(recall_tools))
            _assert("\u94f6\u8272\u7535\u52a8\u8f66" in str(recall_payload.get("content") or ""), str(recall_payload))
            _assert(recall_ms < 5000, f"recall took {recall_ms}ms")

            history = await client.get(
                f"/chat/history/{recall_thread}",
                params={"user_id": str(user_id)},
            )
            _assert(history.status_code == 200, history.text)
            history_payload = history.json()
            history_text = str(history_payload)
            _assert("search_memory" in history_text, history_text)

            print("user-state HTTP runtime verification passed")
            print(f"write_latency_ms={write_ms}")
            print(f"recall_latency_ms={recall_ms}")
            print(f"stored_status={matching[0].get('state_status')}")
    finally:
        await asyncio.sleep(1)
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
