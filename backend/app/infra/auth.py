"""Authentication dependencies for FastAPI.

Provides:
- get_current_user: Dependency to get the current authenticated user
- get_current_user_optional: Optional dependency (returns None if not authenticated)
"""

import logging
from uuid import UUID
from typing import Annotated

from fastapi import Depends, HTTPException, status, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.infra.config import get_settings
from app.infra.security import verify_token
from app.infra.database import get_async_session
from app.crud import get_user
from app.models.user import User


logger = logging.getLogger(__name__)


async def _extract_token_from_request(request: Request) -> str | None:
    """Extract JWT token from request.

    Checks:
    1. HTTP-only cookie
    2. Authorization header (Bearer token)

    Args:
        request: FastAPI request object

    Returns:
        Token string or None
    """
    settings = get_settings()

    # Try cookie first
    token = request.cookies.get(settings.JWT_COOKIE_NAME)
    if token:
        return token

    # Try Authorization header
    auth_header = request.headers.get("Authorization")
    if auth_header and auth_header.startswith("Bearer "):
        return auth_header[7:]  # Remove "Bearer " prefix

    return None


async def get_current_user(
    request: Request,
    session: AsyncSession = Depends(get_async_session),
) -> User:
    """Get the current authenticated user.

    Raises HTTP 401 if not authenticated.

    Args:
        request: FastAPI request object
        session: Database session

    Returns:
        User instance

    Raises:
        HTTPException: 401 if not authenticated
    """
    token = await _extract_token_from_request(request)

    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )

    user_id = verify_token(token)

    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
        )

    try:
        user_uuid = UUID(user_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token subject",
        )

    user = await get_user(session, user_uuid)

    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
        )

    return user


async def get_current_user_optional(
    request: Request,
    session: AsyncSession = Depends(get_async_session),
) -> User | None:
    """Get the current user if authenticated, otherwise None.

    Use this for endpoints that work for both authenticated and anonymous users.

    Args:
        request: FastAPI request object
        session: Database session

    Returns:
        User instance or None
    """
    token = await _extract_token_from_request(request)

    if not token:
        return None

    user_id = verify_token(token)

    if not user_id:
        return None

    try:
        user_uuid = UUID(user_id)
    except ValueError:
        return None

    return await get_user(session, user_uuid)


# Type aliases for dependency injection
CurrentUser = Annotated[User, Depends(get_current_user)]
OptionalUser = Annotated[User | None, Depends(get_current_user_optional)]
