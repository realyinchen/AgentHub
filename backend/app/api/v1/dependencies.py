"""
FastAPI Dependency Injection

Provides database session and other common dependencies for API routes.
Uses the factory's cached singleton to avoid connection pool leaks.
"""

from typing import AsyncGenerator

from app.database.factory import get_database
from app.database.interfaces import DatabaseInterface


async def get_db() -> AsyncGenerator:
    """
    Yield a database session for use in FastAPI dependency injection.

    Uses the factory's cached database singleton, so the engine/connection pool
    is shared across all requests (no pool leak).
    """
    db = get_database()
    async with db.session() as session:
        yield session


def get_database_dep() -> DatabaseInterface:
    """Return the database interface instance for use in tool functions."""
    return get_database()
