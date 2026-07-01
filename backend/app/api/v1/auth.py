"""Authentication API endpoints.

This module provides:
- Mock user login (for demo/testing)
- WeChat QR code login via WebSocket
- Current user info
"""

import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.infra.config import get_settings
from app.infra.database import get_async_session
from app.infra.security import create_access_token
from app.infra.auth import get_current_user_optional
from app.crud import get_user, get_mock_users
from app.models.user import User


logger = logging.getLogger(__name__)


router = APIRouter(prefix="/auth", tags=["auth"])


# ============================================================================
# Request/Response Models
# ============================================================================


class MockLoginRequest(BaseModel):
    """Request for mock user login."""

    user_id: UUID


class UserResponse(BaseModel):
    """User info response."""

    id: UUID
    display_name: str
    is_mock_user: bool

    class Config:
        from_attributes = True


class AuthStatusResponse(BaseModel):
    """Authentication status response."""

    authenticated: bool
    user: UserResponse | None = None


# ============================================================================
# Helper Functions
# ============================================================================


def _create_auth_cookie_response(user: User) -> JSONResponse:
    """Create a response with JWT cookie set.

    Args:
        user: User instance

    Returns:
        JSONResponse with HTTP-only cookie set
    """
    settings = get_settings()

    # Create JWT token
    token = create_access_token(subject=str(user.id))

    # Build cookie response with JSON body
    response = JSONResponse(
        status_code=status.HTTP_200_OK,
        content={"message": "Login successful"},
    )

    response.set_cookie(
        key=settings.JWT_COOKIE_NAME,
        value=token,
        httponly=True,
        secure=settings.JWT_COOKIE_SECURE,
        samesite=settings.JWT_COOKIE_SAMESITE,
        max_age=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        path="/",
    )

    return response


# ============================================================================
# API Endpoints
# ============================================================================


@router.get("/status", response_model=AuthStatusResponse)
async def get_auth_status(
    user: User | None = Depends(get_current_user_optional),
) -> AuthStatusResponse:
    """Get current authentication status.

    Checks if a valid JWT cookie is present and returns user info.
    """
    if user:
        return AuthStatusResponse(
            authenticated=True,
            user=UserResponse.model_validate(user),
        )
    return AuthStatusResponse(authenticated=False)


@router.get("/mock-users")
async def list_mock_users(
    session: AsyncSession = Depends(get_async_session),
) -> list[UserResponse]:
    """List all available mock users for demo login.

    Only available in dev mode.
    """
    settings = get_settings()
    if not settings.is_dev:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Mock login is only available in dev mode",
        )

    users = await get_mock_users(session)
    return [UserResponse.model_validate(u) for u in users]


@router.post("/mock-login")
async def mock_login(
    request: MockLoginRequest,
    session: AsyncSession = Depends(get_async_session),
) -> Response:
    """Login as a mock user (for demo/testing).

    Only available in dev mode.
    Sets an HTTP-only cookie with JWT token.
    """
    settings = get_settings()
    if not settings.is_dev:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Mock login is only available in dev mode",
        )

    # Find the mock user
    user = await get_user(session, request.user_id)
    if user is None or not user.is_mock_user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid mock user ID",
        )

    logger.info(f"Mock login successful: {user.display_name} ({user.id})")
    return _create_auth_cookie_response(user)


@router.post("/logout")
async def logout() -> JSONResponse:
    """Logout by clearing the auth cookie.

    Returns a response that clears the JWT cookie.
    """
    settings = get_settings()

    response = JSONResponse(
        status_code=status.HTTP_200_OK,
        content={"message": "Logout successful"},
    )

    response.delete_cookie(
        key=settings.JWT_COOKIE_NAME,
        path="/",
    )

    return response
