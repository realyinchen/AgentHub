"""
Rate limiting configuration for FastAPI.

Provides API rate limiting using slowapi to prevent abuse and ensure service availability.
"""

from slowapi import Limiter
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from fastapi import Request, Response
from fastapi.responses import JSONResponse

# Create limiter instance with IP-based rate limiting
limiter = Limiter(
    key_func=get_remote_address,
    default_limits=["100/minute"],  # Global default: 100 requests per minute per IP
)


def rate_limit_exceeded_handler(request: Request, exc: RateLimitExceeded) -> Response:
    """
    Custom handler for rate limit exceeded errors.

    Returns a JSON response with 429 status code and helpful message.
    """
    retry_after = 60
    if hasattr(exc, "description") and isinstance(exc.description, dict):
        retry_after = exc.description.get("retry_after", 60)

    return JSONResponse(
        status_code=429,
        content={
            "error": "Rate limit exceeded",
            "message": "Too many requests. Please slow down and try again later.",
            "retry_after": retry_after,
        },
    )


# Endpoint-specific rate limits
class RateLimits:
    """
    Predefined rate limits for different endpoint types.

    Usage:
        @api_router.get("/agents/")
        @limiter.limit(RateLimits.LIST_AGENTS)
        async def list_agents(...)
    """

    # General read operations
    LIST_AGENTS = "30/minute"
    LIST_CONVERSATIONS = "30/minute"
    GET_HISTORY = "20/minute"

    # Write operations
    CREATE_CONVERSATION = "10/minute"
    UPDATE_TITLE = "20/minute"
    DELETE_CONVERSATION = "10/minute"

    # Streaming operations (more restrictive due to long-running connections)
    STREAM_CHAT = "10/minute"

    # Model configuration (admin operations)
    MODEL_CONFIG = "30/minute"
    PROVIDER_CONFIG = "20/minute"

    # Title generation
    GENERATE_TITLE = "15/minute"
