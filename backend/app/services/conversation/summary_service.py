from __future__ import annotations

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.conversation.journal_repository import (
    ConversationEventRepository,
)
from app.services.conversation.summary_builder import (
    SummaryBuildError,
    SummaryBuilder,
)
from app.services.conversation.summary_contracts import (
    ConversationSummary,
    SummaryProvider,
)
from app.services.conversation.summary_repository import (
    ConversationSummaryRepository,
)


class ConversationSummaryService:
    """Coordinate one bounded Journal -> summary append."""

    def __init__(
        self,
        *,
        event_repository: ConversationEventRepository | None = None,
        summary_repository: ConversationSummaryRepository | None = None,
    ) -> None:
        self._events = event_repository or ConversationEventRepository()
        self._summaries = summary_repository or ConversationSummaryRepository()

    async def summarize_next(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        thread_id: UUID,
        provider: SummaryProvider,
        through_sequence: int | None = None,
        source_upper_bound: int | None = None,
    ) -> ConversationSummary:
        previous = await self._summaries.latest(
            db,
            user_id=user_id,
            thread_id=thread_id,
            through_sequence=source_upper_bound,
        )
        page = await self._events.list_events(
            db,
            user_id=user_id,
            thread_id=thread_id,
            after_sequence=previous.to_sequence if previous else 0,
            limit=500,
            through_sequence=source_upper_bound,
        )
        events = [
            event
            for event in page.events
            if through_sequence is None
            or event.sequence_no <= through_sequence
        ]
        while events and events[-1].role != "assistant":
            events.pop()
        if not events:
            raise SummaryBuildError(
                "no new completed exchange is available for summary"
            )
        candidate = await SummaryBuilder(provider).build(
            previous=previous,
            events=events,
        )
        return await self._summaries.save(db, candidate)


__all__ = ["ConversationSummaryService"]
