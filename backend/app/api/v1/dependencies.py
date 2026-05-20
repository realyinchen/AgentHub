"""
FastAPI Dependency Injection

Provides database session and other common dependencies for API routes.
Uses the factory's cached singleton to avoid connection pool leaks.
"""

from dataclasses import dataclass
from typing import Any, AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession

from app.infra.database import get_database
from app.schemas.chat import UserInput


@dataclass
class RequestContext:
    """Request context containing three-level IDs for end-to-end tracing.

    Attributes:
        user_id: User identifier for personalization and memory
        request_id: Unique request identifier for tracing and idempotency
        thread_id: Conversation thread identifier for state persistence
    """

    user_id: str
    request_id: str
    thread_id: str


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """
    Yield a database session for use in FastAPI dependency injection.

    Uses the factory's cached database singleton, so the engine/connection pool
    is shared across all requests (no pool leak).
    """
    db = get_database()
    async with db.session() as session:
        yield session


def get_database_dep() -> Any:
    """Return the database singleton for use in tool functions."""
    return get_database()


async def get_request_context(user_input: UserInput) -> RequestContext:
    """
    Extract and validate three-level IDs from user input.

    All IDs are required by Pydantic validation in UserInput schema.
    This dependency centralizes ID extraction for use across endpoints.

    Args:
        user_input: The validated user input from request body

    Returns:
        RequestContext containing validated three-level IDs
    """
    return RequestContext(
        user_id=user_input.user_id,
        request_id=user_input.request_id,
        thread_id=str(user_input.thread_id),
    )
