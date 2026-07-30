from __future__ import annotations

import re

from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.chat import ChatMessage, UserInput
from app.services.conversation.journal_contracts import (
    AppendConversationEvent,
    AppendConversationLifecycleEvent,
    ConversationJournalEvent,
    ConversationShadowEnrollment,
)
from app.services.conversation.journal_policy import (
    assistant_event_metadata,
    receipt_references,
    user_event_metadata,
)
from app.services.conversation.journal_repository import (
    ConversationEventRepository,
)


class ConversationJournalService:
    """Translate published chat DTOs into immutable journal commands."""

    def __init__(
        self,
        repository: ConversationEventRepository | None = None,
    ) -> None:
        self._repository = repository or ConversationEventRepository()

    async def record_user_message(
        self,
        db: AsyncSession,
        user_input: UserInput,
        *,
        shadow_enrollment: ConversationShadowEnrollment | None = None,
    ) -> ConversationJournalEvent:
        return await self._repository.append(
            db,
            AppendConversationEvent(
                user_id=user_input.user_id,
                thread_id=user_input.thread_id,
                request_id=user_input.request_id,
                role="user",
                content=user_input.content,
                metadata=user_event_metadata(user_input),
                shadow_enrollment=shadow_enrollment,
            ),
        )

    async def record_assistant_message(
        self,
        db: AsyncSession,
        *,
        user_input: UserInput,
        message: ChatMessage,
    ) -> ConversationJournalEvent:
        return await self._repository.append(
            db,
            AppendConversationEvent(
                user_id=user_input.user_id,
                thread_id=user_input.thread_id,
                request_id=user_input.request_id,
                role="assistant",
                content=message.content,
                receipt_refs=receipt_references(message),
                metadata=assistant_event_metadata(message),
            ),
        )

    async def record_clarification(
        self,
        db: AsyncSession,
        *,
        user_input: UserInput,
        question: str,
        receipt_refs: list[str] | None = None,
    ) -> ConversationJournalEvent:
        return await self._repository.append(
            db,
            AppendConversationLifecycleEvent(
                user_id=user_input.user_id,
                thread_id=user_input.thread_id,
                request_id=user_input.request_id,
                event_type="clarification_requested",
                role="assistant",
                content=question,
                receipt_refs=list(receipt_refs or []),
                metadata={"lifecycle": {"status": "waiting_clarification"}},
            ),
        )

    async def record_turn_failed(
        self,
        db: AsyncSession,
        *,
        user_input: UserInput,
        failure_code: str,
    ) -> ConversationJournalEvent:
        candidate = str(failure_code or "").strip().lower()
        safe_code = (
            candidate
            if re.fullmatch(r"[a-z0-9_.-]{1,128}", candidate)
            else "turn_failed"
        )
        return await self._repository.append(
            db,
            AppendConversationLifecycleEvent(
                user_id=user_input.user_id,
                thread_id=user_input.thread_id,
                request_id=user_input.request_id,
                event_type="turn_failed",
                role="system",
                content=safe_code,
                metadata={"lifecycle": {"status": "failed"}},
            ),
        )
