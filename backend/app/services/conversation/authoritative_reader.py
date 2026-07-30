from __future__ import annotations

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.conversation.contracts import (
    ConversationReadRequest,
    ConversationReadResult,
)
from app.services.conversation.journal_reader import read_journal_events
from app.services.conversation.journal_repository import (
    ConversationEventRepository,
)


class JournalConversationReader:
    """Read exact dialogue only from the authoritative ConversationJournal."""

    def __init__(
        self,
        repository: ConversationEventRepository | None = None,
    ) -> None:
        self._repository = repository or ConversationEventRepository()

    async def read(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        thread_id: UUID,
        exclude_request_id: str,
        request: ConversationReadRequest,
    ) -> ConversationReadResult:
        cursor = 0
        dialogue_events = []
        while True:
            page = await self._repository.list_events(
                db,
                user_id=user_id,
                thread_id=thread_id,
                after_sequence=cursor,
                exclude_request_id=exclude_request_id,
                limit=500,
            )
            if page.events:
                cursor = page.events[-1].sequence_no
                dialogue_events.extend(
                    event
                    for event in page.events
                    if event.role in {"user", "assistant"}
                )
            if not page.has_more:
                break
        return read_journal_events(dialogue_events, request)


__all__ = ["JournalConversationReader"]
