"""CRUD operations for UserChannel model."""

from uuid import UUID
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user_channel import UserChannel


async def get_user_channel(session: AsyncSession, channel_id: UUID) -> UserChannel | None:
    """Get a user channel by ID.
    
    Args:
        session: AsyncSession for database operations
        channel_id: UUID of the user channel
        
    Returns:
        UserChannel instance or None if not found
    """
    result = await session.execute(
        select(UserChannel).where(UserChannel.id == channel_id)
    )
    return result.scalar_one_or_none()


async def get_user_channel_by_user_and_channel(
    session: AsyncSession,
    user_id: UUID,
    channel: str,
) -> UserChannel | None:
    """Get a user's channel by channel type.
    
    Args:
        session: AsyncSession for database operations
        user_id: UUID of the user
        channel: Channel type (e.g., 'weixin')
        
    Returns:
        UserChannel instance or None if not found
    """
    result = await session.execute(
        select(UserChannel)
        .where(UserChannel.user_id == user_id)
        .where(UserChannel.channel == channel)
    )
    return result.scalar_one_or_none()


async def get_user_channel_by_channel_user_id(
    session: AsyncSession,
    channel: str,
    channel_user_id: str,
) -> UserChannel | None:
    """Get a user channel by channel type and channel user ID.
    
    This is used to find a user by their channel-specific ID (e.g., WeChat ID).
    
    Args:
        session: AsyncSession for database operations
        channel: Channel type (e.g., 'weixin')
        channel_user_id: Channel-specific user ID (e.g., 'xxx@im.wechat')
        
    Returns:
        UserChannel instance or None if not found
    """
    result = await session.execute(
        select(UserChannel)
        .where(UserChannel.channel == channel)
        .where(UserChannel.channel_user_id == channel_user_id)
    )
    return result.scalar_one_or_none()


async def get_user_channels(session: AsyncSession, user_id: UUID) -> list[UserChannel]:
    """Get all channels for a user.
    
    Args:
        session: AsyncSession for database operations
        user_id: UUID of the user
        
    Returns:
        List of UserChannel instances
    """
    result = await session.execute(
        select(UserChannel)
        .where(UserChannel.user_id == user_id)
        .order_by(UserChannel.created_at)
    )
    return list(result.scalars().all())


async def create_user_channel(
    session: AsyncSession,
    user_id: UUID,
    channel: str,
    channel_user_id: str,
    channel_token: str | None = None,
    channel_base_url: str | None = None,
    channel_token_expires_at: datetime | None = None,
    channel_extra_data: dict | None = None,
) -> UserChannel:
    """Create a new user channel.
    
    Args:
        session: AsyncSession for database operations
        user_id: UUID of the user
        channel: Channel type (e.g., 'weixin')
        channel_user_id: Channel-specific user ID
        channel_token: Optional channel token (will be encrypted)
        channel_base_url: Optional channel API base URL
        channel_token_expires_at: Optional token expiration time
        channel_extra_data: Optional extra data (JSON)
        
    Returns:
        Created UserChannel instance
    """
    user_channel = UserChannel(
        user_id=user_id,
        channel=channel,
        channel_user_id=channel_user_id,
        channel_token=channel_token,
        channel_base_url=channel_base_url,
        channel_token_expires_at=channel_token_expires_at,
        channel_extra_data=channel_extra_data,
    )
    session.add(user_channel)
    await session.flush()
    await session.refresh(user_channel)
    return user_channel


async def update_user_channel(
    session: AsyncSession,
    user_channel: UserChannel,
    **kwargs: Any,
) -> UserChannel:
    """Update user channel fields.
    
    Args:
        session: AsyncSession for database operations
        user_channel: UserChannel instance to update
        **kwargs: Fields to update
        
    Returns:
        Updated UserChannel instance
    """
    for key, value in kwargs.items():
        if hasattr(user_channel, key):
            setattr(user_channel, key, value)
    await session.flush()
    await session.refresh(user_channel)
    return user_channel


async def update_channel_credentials(
    session: AsyncSession,
    user_channel: UserChannel,
    channel_token: str,
    channel_base_url: str,
    expires_in_seconds: int = 24 * 3600,  # Default 24 hours
) -> UserChannel:
    """Update channel credentials after successful authentication.
    
    Args:
        session: AsyncSession for database operations
        user_channel: UserChannel instance to update
        channel_token: New channel token
        channel_base_url: Channel API base URL
        expires_in_seconds: Token expiration time in seconds
        
    Returns:
        Updated UserChannel instance
    """
    now = datetime.now(timezone.utc)
    expires_at = datetime.fromtimestamp(
        now.timestamp() + expires_in_seconds, 
        tz=timezone.utc
    )
    
    return await update_user_channel(
        session,
        user_channel,
        channel_token=channel_token,
        channel_base_url=channel_base_url,
        channel_token_expires_at=expires_at,
    )


async def update_last_contact(
    session: AsyncSession,
    user_channel: UserChannel,
    contact_id: str,
    context_token: str,
) -> UserChannel:
    """Update last contact info for reconnection notifications.
    
    Args:
        session: AsyncSession for database operations
        user_channel: UserChannel instance to update
        contact_id: Last contact user ID
        context_token: Last context token
        
    Returns:
        Updated UserChannel instance
    """
    return await update_user_channel(
        session,
        user_channel,
        last_contact_id=contact_id,
        last_context_token=context_token,
    )


async def delete_user_channel(session: AsyncSession, user_channel: UserChannel) -> None:
    """Delete a user channel.
    
    Args:
        session: AsyncSession for database operations
        user_channel: UserChannel instance to delete
    """
    await session.delete(user_channel)
    await session.flush()


async def get_or_create_user_channel(
    session: AsyncSession,
    user_id: UUID,
    channel: str,
    channel_user_id: str,
    **kwargs: Any,
) -> UserChannel:
    """Get existing user channel or create a new one.
    
    Args:
        session: AsyncSession for database operations
        user_id: UUID of the user
        channel: Channel type (e.g., 'weixin')
        channel_user_id: Channel-specific user ID
        **kwargs: Additional fields for creation
        
    Returns:
        UserChannel instance (existing or newly created)
    """
    user_channel = await get_user_channel_by_channel_user_id(
        session, channel, channel_user_id
    )
    
    if user_channel:
        return user_channel
    
    return await create_user_channel(
        session,
        user_id=user_id,
        channel=channel,
        channel_user_id=channel_user_id,
        **kwargs,
    )


async def get_weixin_thread_ids(session: AsyncSession) -> set[UUID]:
    """Get all thread IDs (user_channel.id) that belong to WeChat channel.
    
    Used to filter out WeChat threads from Web UI.
    
    Returns:
        Set of thread IDs (UUIDs) that are WeChat channels
    """
    result = await session.execute(
        select(UserChannel.id).where(UserChannel.channel == "weixin")
    )
    return set(row[0] for row in result.all())


async def is_weixin_thread(session: AsyncSession, thread_id: UUID) -> bool:
    """Check if a thread ID belongs to a WeChat channel.
    
    Args:
        session: AsyncSession for database operations
        thread_id: Thread ID to check (user_channel.id)
        
    Returns:
        True if the thread is a WeChat channel
    """
    result = await session.execute(
        select(UserChannel.id).where(
            UserChannel.id == thread_id,
            UserChannel.channel == "weixin",
        )
    )
    return result.scalar_one_or_none() is not None
