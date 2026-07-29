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
    clarification_user_id = uuid.uuid4()
    write_thread = uuid.uuid4()
    recall_thread = uuid.uuid4()
    clarification_thread = uuid.uuid4()
    statement = "\u4f60\u597d\u6211\u662f\u51b0\u9732"
    question = "\u6211\u662f\u8c01\uff1f"
    await _seed_user(user_id)
    await _seed_user(clarification_user_id)
    try:
        async with httpx.AsyncClient(base_url=BASE_URL, timeout=20) as client:
            clarification_response = await client.post(
                "/chat/invoke",
                json={
                    "content": "\u8bb0\u4f4f\u6211\u7684\u540d\u5b57",
                    "user_id": str(clarification_user_id),
                    "thread_id": str(clarification_thread),
                    "request_id": f"http-clarify-{uuid.uuid4()}",
                },
            )
            _assert(
                clarification_response.status_code == 200,
                clarification_response.text,
            )
            clarification_payload = clarification_response.json()
            _assert(
                "\u540d\u5b57\u662f\u4ec0\u4e48"
                in str(clarification_payload.get("content") or ""),
                str(clarification_payload),
            )
            clarification_current = await client.get(
                f"/memory/{clarification_user_id}/current"
            )
            _assert(
                not (
                    clarification_current.json().get("memories")
                    or []
                ),
                clarification_current.text,
            )

            continuation_response = await client.post(
                "/chat/invoke",
                json={
                    "content": "\u5c0f\u96e8",
                    "user_id": str(clarification_user_id),
                    "thread_id": str(clarification_thread),
                    "request_id": f"http-continuation-{uuid.uuid4()}",
                },
            )
            _assert(
                continuation_response.status_code == 200,
                continuation_response.text,
            )
            continuation_payload = continuation_response.json()
            _assert(
                "\u4f60\u7684\u540d\u5b57\u662f\u5c0f\u96e8"
                in str(continuation_payload.get("content") or ""),
                str(continuation_payload),
            )
            continuation_tools = (
                continuation_payload.get("custom_data") or {}
            ).get("tool_info") or []
            _assert(
                [item.get("name") for item in continuation_tools]
                == ["process_memory_write_request"],
                str(continuation_tools),
            )

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
            _assert(trace.get("intent") == "memory_update", str(trace))
            tool_info = custom.get("tool_info") or []
            _assert(
                [item.get("name") for item in tool_info]
                == ["process_memory_write_request"],
                str(tool_info),
            )
            receipt = custom.get("plan_receipt") or {}
            _assert(receipt.get("status") == "completed", str(receipt))
            _assert(
                "\u51b0\u9732" in str(write_payload.get("content") or ""),
                str(write_payload),
            )
            _assert(write_ms < 5000, f"write took {write_ms}ms")

            current_response = await client.get(f"/memory/{user_id}/current")
            _assert(current_response.status_code == 200, current_response.text)
            memories = current_response.json().get("memories") or []
            matching = [
                item
                for item in memories
                if item.get("state_key") == "profile.name"
                and (item.get("state_value") or {}).get("name") == "\u51b0\u9732"
            ]
            _assert(matching, str(memories))

            repeat_response = await client.post(
                "/chat/invoke",
                json={
                    "content": "\u8bb0\u4f4f\u6211\u7684\u540d\u5b57",
                    "user_id": str(user_id),
                    "thread_id": str(write_thread),
                    "request_id": f"http-repeat-{uuid.uuid4()}",
                },
            )
            _assert(repeat_response.status_code == 200, repeat_response.text)
            repeat_payload = repeat_response.json()
            repeat_tools = (
                repeat_payload.get("custom_data") or {}
            ).get("tool_info") or []
            _assert(
                [item.get("name") for item in repeat_tools]
                == ["process_memory_write_request"],
                str(repeat_tools),
            )
            _assert(
                "\u4e0d\u9700\u8981\u91cd\u590d\u4fdd\u5b58"
                in str(repeat_payload.get("content") or ""),
                str(repeat_payload),
            )

            conversation_response = await client.post(
                "/chat/invoke",
                json={
                    "content": "\u6211\u521a\u624d\u8ddf\u4f60\u8bf4\u4ec0\u4e48\u4e86",
                    "user_id": str(user_id),
                    "thread_id": str(write_thread),
                    "request_id": f"http-conversation-{uuid.uuid4()}",
                },
            )
            _assert(
                conversation_response.status_code == 200,
                conversation_response.text,
            )
            conversation_payload = conversation_response.json()
            conversation_tools = (
                conversation_payload.get("custom_data") or {}
            ).get("tool_info") or []
            _assert(
                [item.get("name") for item in conversation_tools]
                == ["recall_recent_conversation"],
                str(conversation_tools),
            )
            conversation_answer = str(
                conversation_payload.get("content") or ""
            )
            _assert(statement in conversation_answer, conversation_answer)
            _assert(
                "\u8bb0\u4f4f\u6211\u7684\u540d\u5b57"
                in conversation_answer,
                conversation_answer,
            )

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
            _assert(
                "\u51b0\u9732" in str(recall_payload.get("content") or ""),
                str(recall_payload),
            )
            _assert(recall_ms < 5000, f"recall took {recall_ms}ms")

            history = await client.get(
                f"/chat/history/{recall_thread}",
                params={"user_id": str(user_id)},
            )
            _assert(history.status_code == 200, history.text)
            history_payload = history.json()
            history_text = str(history_payload)
            _assert("search_memory" in history_text, history_text)

            identity_thread = uuid.uuid4()
            correction_thread = uuid.uuid4()
            identity_lookup_thread = uuid.uuid4()
            for content, thread_id in (
                ("\u6211\u662f\u51b0\u9732", identity_thread),
                (
                    "\u6211\u73b0\u5728\u4e0d\u53eb\u51b0\u9732\uff0c"
                    "\u6211\u73b0\u5728\u53eb\u9c81\u73ed",
                    correction_thread,
                ),
            ):
                identity_write = await client.post(
                    "/chat/invoke",
                    json={
                        "content": content,
                        "user_id": str(user_id),
                        "thread_id": str(thread_id),
                        "request_id": f"http-identity-{uuid.uuid4()}",
                    },
                )
                _assert(identity_write.status_code == 200, identity_write.text)

            identity_lookup = await client.post(
                "/chat/invoke",
                json={
                    "content": "\u6211\u662f\u8c01\uff1f",
                    "user_id": str(user_id),
                    "thread_id": str(identity_lookup_thread),
                    "request_id": f"http-identity-lookup-{uuid.uuid4()}",
                },
            )
            _assert(identity_lookup.status_code == 200, identity_lookup.text)
            identity_payload = identity_lookup.json()
            _assert(
                "\u9c81\u73ed" in str(identity_payload.get("content") or ""),
                str(identity_payload),
            )
            identity_tools = (
                identity_payload.get("custom_data") or {}
            ).get("tool_info") or []
            _assert(
                len(identity_tools) == 1
                and identity_tools[0].get("name") == "search_memory"
                and identity_tools[0].get("status") == "completed",
                str(identity_tools),
            )

            print("user-state HTTP runtime verification passed")
            print(f"write_latency_ms={write_ms}")
            print(f"recall_latency_ms={recall_ms}")
            print(f"stored_status={matching[0].get('state_status')}")
    finally:
        await asyncio.sleep(1)
        await _cleanup(user_id)
        await _cleanup(clarification_user_id)


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
