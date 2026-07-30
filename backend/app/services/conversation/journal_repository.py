from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.chat import Conversation
from app.models.conversation_event import ConversationEventRecord
from app.services.conversation.journal_contracts import (
    AppendConversationEvent,
    AppendConversationLifecycleEvent,
    ConversationJournalEvent,
    ConversationJournalPage,
    ConversationShadowEnrollment,
    LegacyConversationShadowEnrollment,
)
from app.services.conversation.journal_errors import (
    ConversationIdempotencyConflict,
    ConversationLifecycleError,
    ConversationOwnershipError,
)


class ConversationEventRepository:
    """Persist and read immutable conversation events; no projection logic."""

    async def append(
        self,
        db: AsyncSession,
        command: AppendConversationEvent | AppendConversationLifecycleEvent,
    ) -> ConversationJournalEvent:
        conversation = await self._lock_owned_conversation(db, command)
        existing = await self._find_idempotent_event(db, command)
        if existing is not None:
            self._assert_same_payload(existing, command)
            return _event_from_record(existing)
        if command.role != "user":
            await self._require_user_source(db, command)

        conversation.journal_sequence += 1
        record = ConversationEventRecord(
            user_id=command.user_id,
            thread_id=command.thread_id,
            request_id=command.request_id,
            exchange_id=command.exchange_id,
            sequence_no=conversation.journal_sequence,
            event_type=command.event_type,
            role=command.role,
            content=command.content,
            receipt_refs=list(command.receipt_refs),
            metadata_json=dict(command.metadata),
            shadow_enrollment_json=(
                command.shadow_enrollment.model_dump(mode="json")
                if isinstance(command, AppendConversationEvent)
                and command.shadow_enrollment is not None
                else None
            ),
        )
        db.add(record)
        await db.flush()
        await db.refresh(record)
        return _event_from_record(record)

    async def list_events(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        thread_id: UUID,
        after_sequence: int = 0,
        limit: int = 200,
        exclude_request_id: str | None = None,
        through_sequence: int | None = None,
    ) -> ConversationJournalPage:
        await self._require_owned_conversation(
            db,
            user_id=user_id,
            thread_id=thread_id,
        )
        bounded_limit = max(1, min(int(limit), 500))
        stmt = (
            select(ConversationEventRecord)
            .where(
                ConversationEventRecord.user_id == user_id,
                ConversationEventRecord.thread_id == thread_id,
                ConversationEventRecord.sequence_no > max(
                    0,
                    int(after_sequence),
                ),
            )
            .order_by(ConversationEventRecord.sequence_no.asc())
            .limit(bounded_limit + 1)
        )
        if exclude_request_id:
            stmt = stmt.where(
                ConversationEventRecord.request_id != exclude_request_id
            )
        if through_sequence is not None:
            stmt = stmt.where(
                ConversationEventRecord.sequence_no
                <= max(0, int(through_sequence))
            )
        result = await db.execute(stmt)
        records = list(result.scalars().all())
        return ConversationJournalPage(
            events=[
                _event_from_record(item)
                for item in records[:bounded_limit]
            ],
            has_more=len(records) > bounded_limit,
        )

    async def get_request_event(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        thread_id: UUID,
        request_id: str,
        role: str,
    ) -> ConversationJournalEvent | None:
        await self._require_owned_conversation(
            db,
            user_id=user_id,
            thread_id=thread_id,
        )
        result = await db.execute(
            select(ConversationEventRecord).where(
                ConversationEventRecord.user_id == user_id,
                ConversationEventRecord.thread_id == thread_id,
                ConversationEventRecord.request_id == request_id,
                ConversationEventRecord.role == role,
            )
        )
        record = result.scalar_one_or_none()
        return _event_from_record(record) if record is not None else None

    async def _lock_owned_conversation(
        self,
        db: AsyncSession,
        command: AppendConversationEvent | AppendConversationLifecycleEvent,
    ) -> Conversation:
        stmt = (
            select(Conversation)
            .where(
                Conversation.thread_id == command.thread_id,
                Conversation.user_id == command.user_id,
                Conversation.is_deleted.is_(False),
            )
            .with_for_update()
        )
        result = await db.execute(stmt)
        conversation = result.scalar_one_or_none()
        if conversation is None:
            raise ConversationOwnershipError(
                "conversation is missing, deleted, or owned by another user"
            )
        return conversation

    async def _require_owned_conversation(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        thread_id: UUID,
    ) -> None:
        stmt = select(Conversation.thread_id).where(
            Conversation.thread_id == thread_id,
            Conversation.user_id == user_id,
            Conversation.is_deleted.is_(False),
        )
        result = await db.execute(stmt)
        if result.scalar_one_or_none() is None:
            raise ConversationOwnershipError(
                "conversation is missing, deleted, or owned by another user"
            )

    async def _find_idempotent_event(
        self,
        db: AsyncSession,
        command: AppendConversationEvent | AppendConversationLifecycleEvent,
    ) -> ConversationEventRecord | None:
        stmt = select(ConversationEventRecord).where(
            ConversationEventRecord.thread_id == command.thread_id,
            ConversationEventRecord.request_id == command.request_id,
            ConversationEventRecord.event_type == command.event_type,
        )
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    async def _require_user_source(
        self,
        db: AsyncSession,
        command: AppendConversationEvent | AppendConversationLifecycleEvent,
    ) -> None:
        result = await db.execute(
            select(ConversationEventRecord.id).where(
                ConversationEventRecord.user_id == command.user_id,
                ConversationEventRecord.thread_id == command.thread_id,
                ConversationEventRecord.request_id == command.request_id,
                ConversationEventRecord.event_type == "user_message",
            )
        )
        if result.scalar_one_or_none() is None:
            raise ConversationLifecycleError(
                "terminal conversation event requires its user_message"
            )

    def _assert_same_payload(
        self,
        existing: ConversationEventRecord,
        command: AppendConversationEvent | AppendConversationLifecycleEvent,
    ) -> None:
        same = (
            existing.user_id == command.user_id
            and existing.exchange_id == command.exchange_id
            and existing.role == command.role
            and existing.content == command.content
            and list(existing.receipt_refs or []) == command.receipt_refs
            and dict(existing.metadata_json or {}) == command.metadata
        )
        if not same:
            raise ConversationIdempotencyConflict(
                "request_id and role already exist with a different payload"
            )


def _event_from_record(
    record: ConversationEventRecord,
) -> ConversationJournalEvent:
    return ConversationJournalEvent(
        id=record.id,
        user_id=record.user_id,
        thread_id=record.thread_id,
        request_id=record.request_id,
        exchange_id=record.exchange_id,
        sequence_no=record.sequence_no,
        event_type=record.event_type,
        role=record.role,
        content=record.content,
        receipt_refs=list(record.receipt_refs or []),
        metadata=dict(record.metadata_json or {}),
        shadow_enrollment=(
            _shadow_enrollment_from_json(
                record.shadow_enrollment_json
            )
            if record.shadow_enrollment_json is not None
            else None
        ),
        created_at=record.created_at,
    )


def _shadow_enrollment_from_json(value: dict):
    schema_version = str(value.get("schema_version") or "")
    if schema_version == "agent-shadow-enrollment-v1":
        return LegacyConversationShadowEnrollment.model_validate(value)
    return ConversationShadowEnrollment.model_validate(value)
