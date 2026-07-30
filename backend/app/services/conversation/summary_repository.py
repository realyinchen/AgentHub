from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.chat import Conversation
from app.models.conversation_summary import ConversationSummaryRecord
from app.services.conversation.journal_errors import ConversationOwnershipError
from app.services.conversation.summary_builder import SummaryBuildError
from app.services.conversation.summary_contracts import (
    ConversationSummary,
    ConversationSummaryCandidate,
)


class ConversationSummaryRepository:
    """Persist immutable summaries while enforcing one linear summary chain."""

    async def latest(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        thread_id: UUID,
        lock_conversation: bool = False,
        through_sequence: int | None = None,
    ) -> ConversationSummary | None:
        await self._require_conversation(
            db,
            user_id=user_id,
            thread_id=thread_id,
            lock=lock_conversation,
        )
        query = select(ConversationSummaryRecord).where(
            ConversationSummaryRecord.user_id == user_id,
            ConversationSummaryRecord.thread_id == thread_id,
        )
        if through_sequence is not None:
            query = query.where(
                ConversationSummaryRecord.to_sequence
                <= max(0, int(through_sequence))
            )
        result = await db.execute(
            query
            .order_by(
                ConversationSummaryRecord.to_sequence.desc(),
                ConversationSummaryRecord.created_at.desc(),
            )
            .limit(1)
        )
        record = result.scalar_one_or_none()
        return _summary_from_record(record) if record is not None else None

    async def save(
        self,
        db: AsyncSession,
        candidate: ConversationSummaryCandidate,
    ) -> ConversationSummary:
        await self._require_conversation(
            db,
            user_id=candidate.user_id,
            thread_id=candidate.thread_id,
            lock=True,
        )
        existing = await self._find_derivation(db, candidate)
        if existing is not None:
            return _summary_from_record(existing)
        latest = await self._latest_record(
            db,
            user_id=candidate.user_id,
            thread_id=candidate.thread_id,
        )
        latest_id = latest.id if latest is not None else None
        if candidate.previous_summary_id != latest_id:
            raise SummaryBuildError("summary chain head changed before save")
        if latest is not None:
            if candidate.from_sequence != latest.from_sequence:
                raise SummaryBuildError("cumulative summary start changed")
            if candidate.to_sequence <= latest.to_sequence:
                raise SummaryBuildError("summary does not advance the chain")
        record = ConversationSummaryRecord(
            **candidate.model_dump(mode="python")
        )
        db.add(record)
        await db.flush()
        await db.refresh(record)
        return _summary_from_record(record)

    async def _require_conversation(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        thread_id: UUID,
        lock: bool,
    ) -> None:
        stmt = select(Conversation.thread_id).where(
            Conversation.thread_id == thread_id,
            Conversation.user_id == user_id,
            Conversation.is_deleted.is_(False),
        )
        if lock:
            stmt = stmt.with_for_update()
        result = await db.execute(stmt)
        if result.scalar_one_or_none() is None:
            raise ConversationOwnershipError(
                "conversation is missing, deleted, or owned by another user"
            )

    async def _find_derivation(
        self,
        db: AsyncSession,
        candidate: ConversationSummaryCandidate,
    ) -> ConversationSummaryRecord | None:
        result = await db.execute(
            select(ConversationSummaryRecord).where(
                ConversationSummaryRecord.thread_id == candidate.thread_id,
                ConversationSummaryRecord.to_sequence == candidate.to_sequence,
                ConversationSummaryRecord.source_hash == candidate.source_hash,
                ConversationSummaryRecord.prompt_version
                == candidate.prompt_version,
            )
        )
        return result.scalar_one_or_none()

    async def _latest_record(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        thread_id: UUID,
    ) -> ConversationSummaryRecord | None:
        result = await db.execute(
            select(ConversationSummaryRecord)
            .where(
                ConversationSummaryRecord.user_id == user_id,
                ConversationSummaryRecord.thread_id == thread_id,
            )
            .order_by(
                ConversationSummaryRecord.to_sequence.desc(),
                ConversationSummaryRecord.created_at.desc(),
            )
            .limit(1)
        )
        return result.scalar_one_or_none()


def _summary_from_record(
    record: ConversationSummaryRecord,
) -> ConversationSummary:
    return ConversationSummary(
        id=record.id,
        user_id=record.user_id,
        thread_id=record.thread_id,
        from_sequence=record.from_sequence,
        to_sequence=record.to_sequence,
        previous_summary_id=record.previous_summary_id,
        structured_content=record.structured_content,
        source_hash=record.source_hash,
        model_id=record.model_id,
        prompt_version=record.prompt_version,
        created_at=record.created_at,
    )


__all__ = ["ConversationSummaryRepository"]
