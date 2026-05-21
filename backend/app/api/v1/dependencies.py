"""
FastAPI Dependency Injection

Provides database session dependency for API routes.
Uses the factory's cached singleton to avoid connection pool leaks.
"""

from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession

from app.infra.database import get_database


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """
    Yield a database session for use in FastAPI dependency injection.

    Uses the factory's cached database singleton, so the engine/connection pool
    is shared across all requests (no pool leak).
    """
    db = get_database()
    async with db.session() as session:
        yield session
