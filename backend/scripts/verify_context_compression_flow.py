"""Verify Journal-derived summaries and bounded exact Controller context."""

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
from app.services.agent_core.context_assembler import (
    ContextAssembler,
    ContextCompressionRequired,
    ConversationContextLoader,
)
from app.services.agent_core.context_coordinator import (
    ControllerContextCoordinator,
)
from app.services.conversation import (
    AppendConversationEvent,
    ConversationEventRepository,
    ConversationSummaryDraft,
    StructuredConversationSummary,
    SummaryStatement,
)
from scripts.init_database import _init_postgres


class _FixtureSummaryProvider:
    async def summarize(self, *, previous, events):
        requests = (
            list(previous.structured_content.user_requests)
            if previous is not None
            else []
        )
        return ConversationSummaryDraft(
            model_id="fixture-summary-provider",
            structured_content=StructuredConversationSummary(
                user_requests=[
                    *requests,
                    SummaryStatement(
                        text="最早一轮已压缩，精确原文仍保留在 Journal。",
                        source_sequences=[
                            events[0].sequence_no,
                            events[-1].sequence_no,
                        ],
                    ),
                ]
            ),
        )


async def _append(
    *,
    user_id: uuid.UUID,
    thread_id: uuid.UUID,
    request_id: str,
    role: str,
    content: str,
) -> None:
    database = get_database()
    async with database.session() as session:
        await ConversationEventRepository().append(
            session,
            AppendConversationEvent(
                user_id=user_id,
                thread_id=thread_id,
                request_id=request_id,
                role=role,
                content=content,
            ),
        )


async def _run() -> None:
    _init_postgres()
    await init_database_connection()
    database = get_database()
    user_id = uuid.uuid4()
    thread_id = uuid.uuid4()
    current_request_id = "context-current-request"
    try:
        async with database.session() as session:
            await session.execute(
                text(
                    """
                    INSERT INTO public.users (id, display_name, is_mock_user)
                    VALUES (:user_id, 'Context Compression Verify', true)
                    """
                ),
                {"user_id": user_id},
            )
            await session.execute(
                text(
                    """
                    INSERT INTO public.conversations (thread_id, user_id, title)
                    VALUES (:thread_id, :user_id, 'Context Compression Verify')
                    """
                ),
                {"thread_id": thread_id, "user_id": user_id},
            )

        for index in range(21):
            request_id = f"context-history-{index}"
            await _append(
                user_id=user_id,
                thread_id=thread_id,
                request_id=request_id,
                role="user",
                content=f"用户历史消息 {index}",
            )
            await _append(
                user_id=user_id,
                thread_id=thread_id,
                request_id=request_id,
                role="assistant",
                content=f"助手已发布回复 {index}",
            )
        await _append(
            user_id=user_id,
            thread_id=thread_id,
            request_id=current_request_id,
            role="user",
            content="这是当前请求，不能重复进入历史上下文。",
        )

        loader = ConversationContextLoader()
        assembler = ContextAssembler(
            recent_exchange_limit=20,
            token_budget=50_000,
        )
        async with database.session() as session:
            material = await loader.load(
                session,
                user_id=user_id,
                thread_id=thread_id,
                exclude_request_id=current_request_id,
            )
            try:
                assembler.assemble(
                    material,
                    current_user_message="当前输入",
                )
            except ContextCompressionRequired as required:
                if required.through_sequence != 2:
                    raise AssertionError(
                        "compression cutoff did not preserve 20 exact exchanges"
                    )
            else:
                raise AssertionError("uncovered old exchange was silently dropped")

        async with database.session() as session:
            assembled = await ControllerContextCoordinator(
                assembler=assembler
            ).prepare(
                session,
                user_id=user_id,
                thread_id=thread_id,
                current_request_id=current_request_id,
                current_user_message="当前输入",
                summary_provider=_FixtureSummaryProvider(),
            )
            page = await ConversationEventRepository().list_events(
                session,
                user_id=user_id,
                thread_id=thread_id,
                limit=100,
            )

        if not assembled.summary_used:
            raise AssertionError("assembled context did not use current summary")
        if assembled.exact_exchange_count != 20:
            raise AssertionError("recent exact exchange count changed")
        if any(
            "当前请求" in turn.content
            for turn in assembled.snapshot.conversation
        ):
            raise AssertionError("current request was duplicated into history")
        if len(page.events) != 43:
            raise AssertionError("summary creation modified exact Journal history")

        print("context compression verification passed")
        print("summary_source=conversation_journal")
        print("summary_is_derived_cache=true")
        print("recent_exact_exchanges=20")
        print("current_request_excluded=true")
        print("journal_events_preserved=43")
    finally:
        async with database.session() as session:
            await session.execute(
                text("DELETE FROM public.users WHERE id = :user_id"),
                {"user_id": user_id},
            )
        await dispose_database()


if __name__ == "__main__":
    asyncio.run(_run())
