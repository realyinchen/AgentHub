"""Security utilities for JWT authentication."""

from datetime import datetime, timedelta, timezone
from typing import Any

from jose import jwt, JWTError
from passlib.context import CryptContext

from app.infra.config import get_settings


# Password hashing context (for future use if needed)
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def create_access_token(
    subject: str,
    expires_delta: timedelta | None = None,
    additional_claims: dict[str, Any] | None = None,
) -> str:
    """Create a JWT access token.
    
    Args:
        subject: Token subject (usually user ID)
        expires_delta: Optional custom expiration time
        additional_claims: Optional additional claims to include
        
    Returns:
        Encoded JWT string
    """
    settings = get_settings()
    
    # JWT_SECRET_KEY is guaranteed to be set by config validation
    assert settings.JWT_SECRET_KEY is not None
    
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(
            minutes=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES
        )
    
    to_encode = {
        "sub": str(subject),
        "exp": expire,
        "iat": datetime.now(timezone.utc),
    }
    
    if additional_claims:
        to_encode.update(additional_claims)
    
    encoded_jwt = jwt.encode(
        to_encode,
        settings.JWT_SECRET_KEY.get_secret_value(),
        algorithm=settings.JWT_ALGORITHM,
    )
    return encoded_jwt


def decode_access_token(token: str) -> dict[str, Any] | None:
    """Decode and validate a JWT access token.
    
    Args:
        token: Encoded JWT string
        
    Returns:
        Decoded payload or None if invalid
    """
    settings = get_settings()
    
    # JWT_SECRET_KEY is guaranteed to be set by config validation
    assert settings.JWT_SECRET_KEY is not None
    
    try:
        payload = jwt.decode(
            token,
            settings.JWT_SECRET_KEY.get_secret_value(),
            algorithms=[settings.JWT_ALGORITHM],
        )
        return payload
    except JWTError:
        return None


def verify_token(token: str) -> str | None:
    """Verify a JWT token and return the subject (user ID).
    
    Args:
        token: Encoded JWT string
        
    Returns:
        User ID (subject) or None if invalid
    """
    payload = decode_access_token(token)
    if payload is None:
        return None
    return payload.get("sub")