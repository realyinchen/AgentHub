"""CRUD operations for User model."""

from uuid import UUID
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.models.user_channel import UserChannel


async def get_user(session: AsyncSession, user_id: UUID) -> User | None:
    """Get a user by ID.
    
    Args:
        session: AsyncSession for database operations
        user_id: UUID of the user
        
    Returns:
        User instance or None if not found
    """
    result = await session.execute(select(User).where(User.id == user_id))
    return result.scalar_one_or_none()


async def get_user_by_channel_user_id(
    session: AsyncSession, 
    channel: str, 
    channel_user_id: str
) -> User | None:
    """Get a user by channel type and channel user ID.
    
    This is used for channel authentication (e.g., WeChat login).
    
    Args:
        session: AsyncSession for database operations
        channel: Channel type (e.g., 'weixin')
        channel_user_id: Channel-specific user ID (e.g., 'xxx@im.wechat')
        
    Returns:
        User instance or None if not found
    """
    result = await session.execute(
        select(User)
        .join(UserChannel)
        .where(UserChannel.channel == channel)
        .where(UserChannel.channel_user_id == channel_user_id)
    )
    return result.scalar_one_or_none()


async def get_mock_users(session: AsyncSession) -> list[User]:
    """Get all mock users (for demo/testing).
    
    Args:
        session: AsyncSession for database operations
        
    Returns:
        List of mock users
    """
    result = await session.execute(
        select(User).where(User.is_mock_user == True).order_by(User.display_name)
    )
    return list(result.scalars().all())


async def create_user(
    session: AsyncSession,
    display_name: str,
    is_mock_user: bool = False,
) -> User:
    """Create a new user.
    
    Args:
        session: AsyncSession for database operations
        display_name: User's display name
        is_mock_user: Whether this is a mock user for demo/testing
        
    Returns:
        Created User instance
    """
    user = User(
        display_name=display_name,
        is_mock_user=is_mock_user,
    )
    session.add(user)
    await session.flush()
    await session.refresh(user)
    return user


async def update_user(
    session: AsyncSession,
    user: User,
    **kwargs: Any,
) -> User:
    """Update user fields.
    
    Args:
        session: AsyncSession for database operations
        user: User instance to update
        **kwargs: Fields to update
        
    Returns:
        Updated User instance
    """
    for key, value in kwargs.items():
        if hasattr(user, key) and value is not None:
            setattr(user, key, value)
    await session.flush()
    await session.refresh(user)
    return user


async def delete_user(session: AsyncSession, user: User) -> None:
    """Delete a user.
    
    Args:
        session: AsyncSession for database operations
        user: User instance to delete
    """
    await session.delete(user)
    await session.flush()