from uuid import UUID
from datetime import datetime, timezone, timedelta

from sqlalchemy import select, update, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.chat import Conversation
from app.schemas.chat import (
    ConversationCreate,
    ConversationUpdate,
)


async def read_conversation_by_thread_id(
    db: AsyncSession, thread_id: UUID
) -> Conversation | None:
    stmt = select(Conversation).where(
        Conversation.thread_id == thread_id, Conversation.is_deleted.is_(False)
    )
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def create_conversation(
    db: AsyncSession, conversation_in: ConversationCreate
) -> Conversation:
    create_data = conversation_in.model_dump(exclude_unset=True)

    db_obj = Conversation(
        **create_data,
    )

    db.add(db_obj)
    # Ensure ORM/DB defaults (e.g. created_at/updated_at) are populated before response serialization.
    await db.flush()
    await db.refresh(db_obj)

    return db_obj


async def update_conversation_by_thread_id(
    db: AsyncSession, thread_id: UUID, update_data: ConversationUpdate
) -> Conversation | None:
    update_values = update_data.model_dump(exclude_unset=True)
    if not update_values:
        raise ValueError("No fields provided to update")

    stmt = (
        update(Conversation)
        .where(
            Conversation.thread_id == thread_id,
            Conversation.is_deleted.is_(False),
        )
        .values(**update_values)
        .returning(Conversation)
    )

    result = await db.execute(stmt)
    await db.flush()
    updated = result.scalar_one_or_none()

    if not updated:
        return None

    return updated


async def get_daily_conversation_stats(
    db: AsyncSession,
    days: int = 30,
) -> list[dict]:
    """
    Get daily conversation count and token usage statistics for the last N days.

    Args:
        db: Database session
        days: Number of days to look back (default: 30)

    Returns:
        List of dicts with date, count, input_tokens, cache_read,
        output_tokens, reasoning, total_tokens
    """
    # Calculate start date (days ago)
    start_date = datetime.now(timezone.utc) - timedelta(days=days)

    stmt = (
        select(
            func.date(Conversation.created_at).label("date"),
            func.count(Conversation.thread_id).label("count"),
            func.sum(Conversation.input_tokens).label("input_tokens"),
            func.sum(Conversation.cache_read).label("cache_read"),
            func.sum(Conversation.output_tokens).label("output_tokens"),
            func.sum(Conversation.reasoning).label("reasoning"),
            func.sum(Conversation.total_tokens).label("total_tokens"),
        )
        .where(
            Conversation.is_deleted.is_(False),
            Conversation.created_at >= start_date,
        )
        .group_by(func.date(Conversation.created_at))
        .order_by("date")
    )

    result = await db.execute(stmt)
    rows = result.all()

    return [
        {
            "date": str(row.date),
            "count": row.count,
            "input_tokens": row.input_tokens,
            "cache_read": row.cache_read,
            "output_tokens": row.output_tokens,
            "reasoning": row.reasoning,
            "total_tokens": row.total_tokens,
        }
        for row in rows
    ]


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
    await db.flush()
    deleted = result.scalar_one_or_none()

    return bool(deleted)


async def list_traces(
    db: AsyncSession,
    hours: int,
    agent_id: str,
    page: int,
    page_size: int,
) -> tuple[list[Conversation], int]:
    """List conversations as traces with time/agent filtering and pagination.

    Args:
        db: Database session
        hours: Filter to conversations updated within the last N hours
        agent_id: Agent ID to filter by, or "all" to include every agent
        page: 0-indexed page number
        page_size: Number of items per page

    Returns:
        Tuple of (conversations for the requested page, total matching count).
    """
    time_cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)

    base_query = select(Conversation).where(
        Conversation.updated_at >= time_cutoff,
        Conversation.is_deleted.is_(False),
    )

    if agent_id != "all":
        base_query = base_query.where(Conversation.agent_id == agent_id)

    count_stmt = select(func.count()).select_from(base_query.subquery())
    count_result = await db.execute(count_stmt)
    total = count_result.scalar() or 0

    convs_stmt = (
        base_query.order_by(Conversation.updated_at.desc())
        .offset(page * page_size)
        .limit(page_size)
    )
    convs_result = await db.execute(convs_stmt)
    convs = convs_result.scalars().all()

    return list(convs), total


async def list_conversations(
    db: AsyncSession, limit: int = 20, offset: int = 0
) -> tuple[list[Conversation], int]:
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

    return list(convs), total


async def update_conversation_tokens(
    db: AsyncSession,
    thread_id: UUID,
    input_tokens: int = 0,
    cache_read: int = 0,
    output_tokens: int = 0,
    reasoning: int = 0,
    total_tokens: int = 0,
) -> Conversation | None:
    """Update conversation token usage by accumulating the new values.

    Args:
        db: Database session
        thread_id: Conversation thread ID
        input_tokens: New input tokens to add
        cache_read: New cache read tokens to add
        output_tokens: New output tokens to add
        reasoning: New reasoning tokens to add
        total_tokens: New total tokens to add

    Returns:
        Updated conversation or None if not found
    """
    stmt = (
        update(Conversation)
        .where(
            Conversation.thread_id == thread_id,
            Conversation.is_deleted.is_(False),
        )
        .values(
            input_tokens=Conversation.input_tokens + input_tokens,
            cache_read=Conversation.cache_read + cache_read,
            output_tokens=Conversation.output_tokens + output_tokens,
            reasoning=Conversation.reasoning + reasoning,
            total_tokens=Conversation.total_tokens + total_tokens,
        )
        .returning(Conversation)
    )

    result = await db.execute(stmt)
    await db.flush()
    updated = result.scalar_one_or_none()

    if not updated:
        return None

    return updated
