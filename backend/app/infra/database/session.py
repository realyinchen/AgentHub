"""Database session management for FastAPI dependency injection."""

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession

from app.infra.database.factory import get_database


async def get_async_session() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency for async database session.
    
    Yields:
        AsyncSession: Database session with auto-commit/rollback.
        
    Usage:
        @router.get("/users")
        async def get_users(session: AsyncSession = Depends(get_async_session)):
            ...
    """
    db = get_database()
    async with db.session() as session:
        yield session