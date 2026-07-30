"""Verify working state can be rebuilt from Journal without message checkpoints."""

from __future__ import annotations

import asyncio
import sys
import uuid
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

load_dotenv(BACKEND_DIR / ".env")

from app.infra.database import (
    dispose_database,
    get_database,
    init_database_connection,
)
from app.services.agent_core.working_state import (
    WorkingStateRecoveryService,
)
from app.services.conversation import (
    AppendConversationEvent,
    AppendConversationLifecycleEvent,
    ConversationEventRepository,
    ConversationLifecycleError,
)
from scripts.init_database import _init_postgres


async def _append(command) -> None:
    database = get_database()
    async with database.session() as session:
        await ConversationEventRepository().append(session, command)


async def _rebuild(user_id: uuid.UUID, thread_id: uuid.UUID):
    database = get_database()
    async with database.session() as session:
        return await WorkingStateRecoveryService().rebuild(
            session,
            user_id=user_id,
            thread_id=thread_id,
        )


async def _run() -> None:
    _init_postgres()
    await init_database_connection()
    database = get_database()
    user_id = uuid.uuid4()
    thread_id = uuid.uuid4()
    try:
        async with database.session() as session:
            await session.execute(
                text(
                    """
                    INSERT INTO public.users (id, display_name, is_mock_user)
                    VALUES (:user_id, 'Working State Verify', true)
                    """
                ),
                {"user_id": user_id},
            )
            await session.execute(
                text(
                    """
                    INSERT INTO public.conversations (thread_id, user_id, title)
                    VALUES (:thread_id, :user_id, 'Working State Verify')
                    """
                ),
                {"thread_id": thread_id, "user_id": user_id},
            )

        first_user = AppendConversationEvent(
            user_id=user_id,
            thread_id=thread_id,
            request_id="working-state-1",
            role="user",
            content="记住我的名字。",
        )
        await _append(first_user)
        await _append(
            AppendConversationLifecycleEvent(
                user_id=user_id,
                thread_id=thread_id,
                request_id="working-state-1",
                event_type="clarification_requested",
                role="assistant",
                content="请告诉我你的名字。",
            )
        )
        waiting = await _rebuild(user_id, thread_id)
        if waiting.last_turn_status != "waiting_clarification":
            raise AssertionError("clarification state was not rebuilt")
        if waiting.pending_clarification is None:
            raise AssertionError("pending clarification was lost")

        second_user = AppendConversationEvent(
            user_id=user_id,
            thread_id=thread_id,
            request_id="working-state-2",
            role="user",
            content="冰露。",
        )
        await _append(second_user)
        resumed = await _rebuild(user_id, thread_id)
        if resumed.pending_clarification is not None:
            raise AssertionError("later user input did not clear old pending state")
        if resumed.active_exchange_id != second_user.exchange_id:
            raise AssertionError("active exchange was not rebuilt")

        await _append(
            AppendConversationLifecycleEvent(
                user_id=user_id,
                thread_id=thread_id,
                request_id="working-state-2",
                event_type="turn_failed",
                role="system",
                content="runtime_failed",
            )
        )
        failed = await _rebuild(user_id, thread_id)
        if failed.last_turn_status != "failed":
            raise AssertionError("failed terminal state was not rebuilt")
        if failed.active_exchange_id is not None:
            raise AssertionError("failed exchange remained active")
        if "messages" in failed.checkpoint_payload():
            raise AssertionError("checkpoint payload contains message history")

        try:
            await _append(
                AppendConversationEvent(
                    user_id=user_id,
                    thread_id=thread_id,
                    request_id="working-state-2",
                    role="assistant",
                    content="不应与失败终态并存。",
                )
            )
        except IntegrityError:
            pass
        else:
            raise AssertionError("multiple terminal events were not rejected")

        try:
            await _append(
                AppendConversationLifecycleEvent(
                    user_id=user_id,
                    thread_id=thread_id,
                    request_id="orphan-terminal",
                    event_type="turn_failed",
                    role="system",
                    content="runtime_failed",
                )
            )
        except ConversationLifecycleError:
            pass
        else:
            raise AssertionError("orphan terminal event was not rejected")

        print("working state rebuild verification passed")
        print("checkpoint_messages=0")
        print("clarification_recovered=true")
        print("failed_turn_terminal=true")
        print("terminal_events_per_request=1")
        print("orphan_terminal_events=0")
    finally:
        async with database.session() as session:
            await session.execute(
                text("DELETE FROM public.users WHERE id = :user_id"),
                {"user_id": user_id},
            )
        await dispose_database()


if __name__ == "__main__":
    asyncio.run(_run())
