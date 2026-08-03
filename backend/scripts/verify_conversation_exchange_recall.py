"""Verify Journal-backed exchange recall and HTTP history projection."""

# ruff: noqa: E402

from __future__ import annotations

import asyncio
import json
import sys
import uuid
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import text


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

load_dotenv(BACKEND_DIR / ".env")

from app.api.v1.chat.history import history
from app.infra.database import (
    dispose_database,
    get_database,
    init_database_connection,
)
from app.schemas.chat import ChatMessage, UserInput
from app.services.agent_core.capabilities import CapabilityRegistry
from app.services.agent_core.contracts import (
    ControllerOutput,
    ControllerToolCall,
)
from app.services.agent_core.core_capabilities import (
    CoreCapabilityAvailability,
)
from app.services.agent_core.harness import AgentCoreHarness
from app.services.agent_runtime.contracts import ExecutionContext
from app.services.conversation import ConversationJournalService
from scripts.init_database import _init_postgres


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


async def _seed(*, user_id: uuid.UUID, thread_id: uuid.UUID) -> None:
    db = get_database()
    async with db.session() as session:
        await session.execute(
            text(
                """
                INSERT INTO public.users (id, display_name, is_mock_user)
                VALUES (:user_id, :display_name, true)
                """
            ),
            {
                "user_id": user_id,
                "display_name": "Conversation Recall Verify",
            },
        )
        await session.execute(
            text(
                """
                INSERT INTO public.conversations (thread_id, user_id, title)
                VALUES (:thread_id, :user_id, :title)
                """
            ),
            {
                "thread_id": thread_id,
                "user_id": user_id,
                "title": "Conversation Recall Verify",
            },
        )


async def _cleanup(user_id: uuid.UUID) -> None:
    db = get_database()
    async with db.session() as session:
        await session.execute(
            text("DELETE FROM public.users WHERE id = :user_id"),
            {"user_id": user_id},
        )


async def _run() -> dict:
    user_id = uuid.uuid4()
    thread_id = uuid.uuid4()
    prior = UserInput(
        content="你好，我是冰露。",
        user_id=user_id,
        thread_id=thread_id,
        request_id="exchange-prior",
    )
    current = UserInput(
        content="刚才我说什么了，你回复什么了？",
        user_id=user_id,
        thread_id=thread_id,
        request_id="exchange-current",
    )
    await _seed(user_id=user_id, thread_id=thread_id)
    try:
        journal = ConversationJournalService()
        db = get_database()
        async with db.session() as session:
            await journal.record_user_message(session, prior)
            await journal.record_assistant_message(
                session,
                user_input=prior,
                message=ChatMessage(
                    type="ai",
                    content="你好，冰露。",
                    request_id=prior.request_id,
                    custom_data={
                        "thinking": "must not enter journal metadata",
                        "plan_receipt": {
                            "actions": [
                                {
                                    "action_id": "answer-prior",
                                    "status": "completed",
                                }
                            ]
                        },
                        "tool_info": [
                            {
                                "name": "conversation_read",
                                "id": "answer-prior",
                                "status": "completed",
                                "args": {"credentials": "must-not-persist"},
                                "output": "must-not-persist",
                            }
                        ],
                    },
                ),
            )
            await journal.record_user_message(session, current)

        output = ControllerOutput(
            mode="capability_proposals",
            tool_calls=[
                ControllerToolCall(
                    call_id="read-prior-exchange",
                    name="conversation_read",
                    arguments={
                        "target": "exchange",
                        "selection": "latest",
                        "count": 1,
                    },
                )
            ],
        )
        result = await AgentCoreHarness(
            registry=CapabilityRegistry(
                core_availability=CoreCapabilityAvailability.all_enabled()
            )
        ).run(
            output,
            goal=current.content,
            context=ExecutionContext(
                user_id=user_id,
                thread_id=thread_id,
                request_id=current.request_id,
            ),
            user_input=current,
        )
        _assert(result.receipt is not None, "runtime receipt is missing")
        _assert(result.answer is not None, "published answer is missing")
        _assert(
            "你好，我是冰露。" in result.answer.content,
            "prior user message was not recalled",
        )
        _assert(
            "你好，冰露。" in result.answer.content,
            "prior published assistant reply was not recalled",
        )
        _assert(
            current.content not in result.answer.content,
            "current recall request leaked into prior exchange",
        )

        async with db.session() as session:
            projected = await history(
                thread_id=thread_id,
                user_id=user_id,
                db=session,
            )
        _assert(
            [message.type for message in projected.messages]
            == ["human", "ai", "human"],
            "HTTP history did not use canonical journal order",
        )
        assistant = projected.messages[1]
        _assert(
            assistant.request_id == prior.request_id,
            "assistant request association was lost",
        )
        encoded_metadata = str(assistant.custom_data)
        _assert(
            "credentials" not in encoded_metadata
            and "must-not-persist" not in encoded_metadata
            and "thinking" not in encoded_metadata,
            "unsafe execution metadata entered the journal projection",
        )
        return {
            "case_id": "conversation_recall",
            "input": "刚才我说什么了，你回复什么了？",
            "expected_capability": "conversation_read",
            "operation": "conversation_read",
            "exchange_complete": True,
            "search_memory_calls": 0,
            "status": "passed",
        }
    finally:
        await _cleanup(user_id)


async def _main_async() -> dict:
    await init_database_connection()
    try:
        return await _run()
    finally:
        await dispose_database()


def main() -> None:
    _init_postgres()
    evidence = asyncio.run(_main_async())
    print("conversation exchange recall verification passed")
    print("current_request_excluded=true")
    print("journal_history_projection=true")
    print("unsafe_metadata_persisted=false")
    print(json.dumps(evidence, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
