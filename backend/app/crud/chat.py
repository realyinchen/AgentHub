from uuid import UUID
from typing import List

from sqlalchemy import select, update, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.chat import Conversation
from app.schemas.chat import (
    ConversationCreate,
    ConversationUpdate,
    ConversationInDB,
)


async def read_conversation_by_thread_id(
    db: AsyncSession, thread_id: UUID
) -> ConversationInDB | None:
    stmt = select(Conversation).where(
        Conversation.thread_id == thread_id, Conversation.is_deleted.is_(False)
    )
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def read_conversation(
    db: AsyncSession, thread_id: UUID
) -> ConversationInDB | None:
    stmt = select(Conversation).where(
        Conversation.thread_id == thread_id, Conversation.is_deleted.is_(False)
    )
    result = await db.execute(stmt)
    conv = result.scalar_one_or_none()

    if not conv:
        return None

    return ConversationInDB.model_validate(conv)


async def create_conversation(
    db: AsyncSession, conversation_in: ConversationCreate
) -> ConversationInDB:
    create_data = conversation_in.model_dump(exclude_unset=True)

    db_obj = Conversation(
        **create_data,
    )

    db.add(db_obj)

    return db_obj


async def update_conversation_by_thread_id(
    db: AsyncSession, update_data: ConversationUpdate
) -> ConversationInDB | None:
    if update_data.model_dump(exclude_unset=True) == {}:
        raise ValueError("No fields provided to update")

    stmt = (
        update(Conversation)
        .where(
            Conversation.thread_id == update_data.thread_id,
            Conversation.is_deleted.is_(False),
        )
        .values(**update_data.model_dump(exclude_unset=True))
        .returning(Conversation)
    )

    result = await db.execute(stmt)
    updated = result.scalar_one_or_none()

    if not updated:
        return None

    return updated


async def soft_delete_conversation_by_thread_id(
    db: AsyncSession, thread_id: UUID
) -> bool:
    stmt = (
        update(Conversation)
        .where(
            Conversation.thread_id == thread_id,
            Conversation.is_deleted.is_(False),
        )
        .values(is_deleted=True)
        .returning(Conversation.thread_id)
    )

    result = await db.execute(stmt)
    deleted = result.scalar_one_or_none()

    return bool(deleted)


async def list_conversations(
    db: AsyncSession, limit: int = 20, offset: int = 0
) -> tuple[List[ConversationInDB], int]:
    stmt = (
        select(Conversation)
        .where(Conversation.is_deleted.is_(False))
        .order_by(Conversation.updated_at.desc())
        .offset(offset)
        .limit(limit)
    )

    count_stmt = (
        select(func.count())
        .select_from(Conversation)
        .where(Conversation.is_deleted.is_(False))
    )

    result = await db.execute(stmt)
    convs = result.scalars().all()

    total_result = await db.execute(count_stmt)
    total = total_result.scalar_one()

    return [ConversationInDB.model_validate(c) for c in convs], total
