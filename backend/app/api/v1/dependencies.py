"""
FastAPI Dependency Injection

Provides database session dependency for API routes.
Uses the factory's cached singleton to avoid connection pool leaks.

Best Practice (FastAPI):
    Use `Annotated` type aliases for cleaner dependency injection:

        from app.api.v1.dependencies import DBSession

        @router.get("/items")
        async def list_items(db: DBSession):
            ...
"""

from typing import Annotated, AsyncGenerator

from fastapi import Depends
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


# Type alias for cleaner dependency injection in route handlers
# Usage: `db: DBSession` instead of `db: AsyncSession = Depends(get_db)`
DBSession = Annotated[AsyncSession, Depends(get_db)]
