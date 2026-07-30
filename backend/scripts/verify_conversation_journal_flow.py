"""Verify the authoritative conversation journal against PostgreSQL."""

from __future__ import annotations

import asyncio
import sys
import uuid
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import text


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

load_dotenv(BACKEND_DIR / ".env")

from app.infra.database import (
    dispose_database,
    get_database,
    init_database_connection,
)
from app.services.conversation import (
    AppendConversationEvent,
    ConversationEventRepository,
    ConversationIdempotencyConflict,
    ConversationOwnershipError,
    ConversationReadRequest,
    read_journal_events,
)
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
                ON CONFLICT (id) DO NOTHING
                """
            ),
            {
                "user_id": user_id,
                "display_name": "Conversation Journal Verify",
            },
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
                "title": "Conversation Journal Verify",
            },
        )


async def _append(command: AppendConversationEvent):
    db = get_database()
    async with db.session() as session:
        return await ConversationEventRepository().append(session, command)


async def _cleanup(user_id: uuid.UUID) -> None:
    db = get_database()
    async with db.session() as session:
        await session.execute(
            text("DELETE FROM public.users WHERE id = :user_id"),
            {"user_id": user_id},
        )


async def _run() -> None:
    user_id = uuid.uuid4()
    stranger_id = uuid.uuid4()
    thread_id = uuid.uuid4()
    await _seed(user_id=user_id, thread_id=thread_id)
    try:
        user_command = AppendConversationEvent(
            user_id=user_id,
            thread_id=thread_id,
            request_id="journal-req-1",
            role="user",
            content="我刚才说了什么？",
        )
        first = await _append(user_command)
        duplicate = await _append(user_command)
        _assert(first.id == duplicate.id, "idempotent append created a duplicate")
        _assert(
            first.sequence_no == duplicate.sequence_no == 1,
            "idempotent append consumed a sequence",
        )

        conflict = user_command.model_copy(
            update={"content": "同一幂等键的不同内容"}
        )
        try:
            await _append(conflict)
        except ConversationIdempotencyConflict:
            pass
        else:
            raise AssertionError("idempotency conflict was not rejected")

        assistant = await _append(
            AppendConversationEvent(
                user_id=user_id,
                thread_id=thread_id,
                request_id="journal-req-1",
                role="assistant",
                content="你问了：我刚才说了什么？",
                receipt_refs=["publish-journal-req-1"],
            )
        )
        _assert(
            assistant.exchange_id == first.exchange_id,
            "request events did not share one exchange",
        )

        concurrent = await asyncio.gather(
            _append(
                AppendConversationEvent(
                    user_id=user_id,
                    thread_id=thread_id,
                    request_id="journal-req-2",
                    role="user",
                    content="第二轮",
                )
            ),
            _append(
                AppendConversationEvent(
                    user_id=user_id,
                    thread_id=thread_id,
                    request_id="journal-req-3",
                    role="user",
                    content="第三轮",
                )
            ),
        )
        _assert(
            sorted(item.sequence_no for item in concurrent) == [3, 4],
            "concurrent appends did not allocate unique monotonic sequences",
        )

        db = get_database()
        async with db.session() as session:
            page = await ConversationEventRepository().list_events(
                session,
                user_id=user_id,
                thread_id=thread_id,
            )
        _assert(
            [event.sequence_no for event in page.events] == [1, 2, 3, 4],
            "journal read is not sequence ordered",
        )
        exchange = read_journal_events(
            page.events,
            ConversationReadRequest(target="exchange"),
        )
        _assert(
            exchange.exchanges[0].user.content == "我刚才说了什么？",
            "journal exchange lost the user message",
        )
        _assert(
            exchange.exchanges[0].assistant is not None
            and exchange.exchanges[0].assistant.content
            == "你问了：我刚才说了什么？",
            "journal exchange lost the published assistant reply",
        )

        async with db.session() as session:
            try:
                await ConversationEventRepository().list_events(
                    session,
                    user_id=stranger_id,
                    thread_id=thread_id,
                )
            except ConversationOwnershipError:
                pass
            else:
                raise AssertionError("cross-user journal read was not rejected")
    finally:
        await _cleanup(user_id)


async def _main_async() -> None:
    await init_database_connection()
    try:
        await _run()
    finally:
        await dispose_database()


def main() -> None:
    _init_postgres()
    asyncio.run(_main_async())
    print("conversation journal verification passed")
    print("idempotency=stable")
    print("sequence=monotonic")
    print("exchange_pairing=exact")
    print("cross_user_read=rejected")


if __name__ == "__main__":
    main()
