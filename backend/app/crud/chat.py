from uuid import UUID
from datetime import datetime, timezone, timedelta

from sqlalchemy import select, update, func, not_
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.chat import Conversation
from app.models.user_channel import UserChannel
from app.schemas.chat import (
    ConversationCreate,
    ConversationUpdate,
)


async def read_conversation_by_thread_id(
    db: AsyncSession,
    thread_id: UUID,
    user_id: UUID,
) -> Conversation | None:
    stmt = select(Conversation).where(
        Conversation.thread_id == thread_id,
        Conversation.user_id == user_id,
        Conversation.is_deleted.is_(False),
    )
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def get_or_create_conversation_by_thread_id(
    db: AsyncSession,
    thread_id: UUID,
    user_id: UUID,
    title: str = "New Conversation",
) -> Conversation:
    """Get or create a conversation by thread_id.

    Used by third-party channel listeners (WeChat, Telegram, etc.) to ensure
    a Conversation record exists for the user_channel.id thread_id, satisfying
    the trace_executions foreign key constraint.

    Args:
        db: Database session
        thread_id: Thread ID (typically user_channel.id for third-party channels)
        user_id: User ID
        title: Title for new conversation

    Returns:
        Existing or newly created Conversation
    """
    # Try to get existing conversation (including deleted ones)
    stmt = select(Conversation).where(
        Conversation.thread_id == thread_id,
        Conversation.user_id == user_id,
    )
    result = await db.execute(stmt)
    existing = result.scalar_one_or_none()

    if existing is not None:
        # If deleted, restore it
        if existing.is_deleted:
            existing.is_deleted = False
            existing.title = title
            await db.flush()
        return existing

    # Create new conversation with specified thread_id
    conversation = Conversation(
        thread_id=thread_id,
        user_id=user_id,
        title=title,
    )
    db.add(conversation)
    await db.flush()
    await db.refresh(conversation)
    return conversation


async def create_conversation(
    db: AsyncSession,
    conversation_in: ConversationCreate,
    user_id: UUID,
) -> Conversation:
    create_data = conversation_in.model_dump(exclude_unset=True)
    create_data["user_id"] = user_id

    db_obj = Conversation(
        **create_data,
    )

    db.add(db_obj)
    await db.flush()
    await db.refresh(db_obj)

    return db_obj


async def update_conversation_by_thread_id(
    db: AsyncSession,
    thread_id: UUID,
    update_data: ConversationUpdate,
    user_id: UUID,
) -> Conversation | None:
    update_values = update_data.model_dump(exclude_unset=True)
    if not update_values:
        return None

    stmt = (
        update(Conversation)
        .where(
            Conversation.thread_id == thread_id,
            Conversation.user_id == user_id,
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
    user_id: UUID | None = None,
) -> list[dict]:
    """
    Get daily conversation count and token usage statistics for the last N days.

    Args:
        db: Database session
        days: Number of days to look back (default: 30)
        user_id: Optional user scope filter

    Returns:
        List of dicts with date, count, input_tokens, output_tokens,
        total_tokens
    """
    start_date = datetime.now(timezone.utc) - timedelta(days=days)

    conditions = [
        Conversation.is_deleted.is_(False),
        Conversation.created_at >= start_date,
    ]
    if user_id:
        conditions.append(Conversation.user_id == user_id)

    stmt = (
        select(
            func.date(Conversation.created_at).label("date"),
            func.count(Conversation.thread_id).label("count"),
            func.sum(Conversation.input_tokens).label("input_tokens"),
            func.sum(Conversation.output_tokens).label("output_tokens"),
            func.sum(Conversation.total_tokens).label("total_tokens"),
        )
        .where(*conditions)
        .group_by(func.date(Conversation.created_at))
        .order_by("date")
    )

    result = await db.execute(stmt)
    rows = result.all()

    return [
        {
            "date": str(row.date),
            "conversation_count": row.count,
            "input_tokens": row.input_tokens,
            "output_tokens": row.output_tokens,
            "total_tokens": row.total_tokens,
        }
        for row in rows
    ]


async def soft_delete_conversation_by_thread_id(
    db: AsyncSession,
    thread_id: UUID,
    user_id: UUID,
) -> bool:
    stmt = (
        update(Conversation)
        .where(
            Conversation.thread_id == thread_id,
            Conversation.user_id == user_id,
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
    page: int,
    page_size: int,
    user_id: UUID,
) -> tuple[list[Conversation], int]:
    """List conversations as traces with time filtering and pagination.

    Args:
        db: Database session
        hours: Filter to conversations updated within the last N hours
        page: 0-indexed page number
        page_size: Number of items per page
        user_id: User scope filter

    Returns:
        Tuple of (conversations for the requested page, total matching count).
    """
    time_cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)

    base_query = select(Conversation).where(
        Conversation.user_id == user_id,
        Conversation.updated_at >= time_cutoff,
        Conversation.is_deleted.is_(False),
    )

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
    db: AsyncSession,
    user_id: UUID,
    limit: int = 20,
    offset: int = 0,
    exclude_weixin: bool = True,
) -> tuple[list[Conversation], int]:
    """List conversations for a user.
    
    Args:
        db: Database session
        user_id: User ID to scope conversations
        limit: Maximum number of conversations to return
        offset: Number of conversations to skip
        exclude_weixin: If True, exclude WeChat thread conversations
        
    Returns:
        Tuple of (conversations, total count)
    """
    # Build base conditions
    conditions = [
        Conversation.user_id == user_id,
        Conversation.is_deleted.is_(False),
    ]
    
    # Exclude WeChat threads: thread_id NOT IN (user_channels.id where channel='weixin')
    if exclude_weixin:
        weixin_subquery = select(UserChannel.id).where(UserChannel.channel == "weixin")
        conditions.append(
            not_(Conversation.thread_id.in_(weixin_subquery))
        )
    
    # Main query
    stmt = (
        select(Conversation)
        .where(*conditions)
        .order_by(Conversation.updated_at.desc())
        .offset(offset)
        .limit(limit)
    )
    
    # Count query
    count_stmt = select(func.count()).select_from(Conversation).where(*conditions)
    
    result = await db.execute(stmt)
    convs = result.scalars().all()
    
    total_result = await db.execute(count_stmt)
    total = total_result.scalar_one()
    
    return list(convs), total


async def update_conversation_tokens(
    db: AsyncSession,
    thread_id: UUID,
    input_tokens: int = 0,
    output_tokens: int = 0,
    total_tokens: int = 0,
) -> Conversation | None:
    """Update conversation token usage by accumulating the new values.

    Args:
        db: Database session
        thread_id: Conversation thread ID
        input_tokens: New input tokens to add
        output_tokens: New output tokens to add
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
            output_tokens=Conversation.output_tokens + output_tokens,
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


async def get_latest_model_name(
    db: AsyncSession,
    thread_id: UUID,
) -> str | None:
    """Return the model_name from the most recent trace in a thread.

    Convenience re-export for API layer — delegates to trace crud.

    Returns:
        Model name string, or None if no trace exists.
    """
    from app.crud.trace import get_latest_model_name as _get

    return await _get(db, thread_id)
