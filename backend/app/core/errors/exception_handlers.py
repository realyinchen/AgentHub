"""
FastAPI exception handlers for centralized error handling.

This module provides exception handlers that can be registered with the
FastAPI application to ensure consistent and user-friendly error responses.
"""

import logging
from typing import Any

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.responses import JSONResponse

from app.core.errors.exceptions import (
    LLMBaseError,
    extract_error_context,
    get_user_friendly_error_message,
)


logger = logging.getLogger(__name__)


# ==============================================================================
# Exception Handler Functions
# ==============================================================================


async def http_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """
    Handle HTTPExceptions raised by business logic.

    These exceptions are explicitly raised by the application code and are
    considered safe to show to users.
    """
    assert isinstance(exc, HTTPException)

    # Log the error for debugging
    logger.warning(
        "HTTPException: status_code=%s, detail=%s, path=%s, method=%s",
        exc.status_code,
        exc.detail,
        request.url.path,
        request.method,
    )

    # For HTTPExceptions, we return the detail as-is since they're
    # explicitly raised by business logic and should be user-friendly
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "detail": str(exc.detail),
            "error_type": "http_exception",
        },
    )


async def llm_base_error_handler(request: Request, exc: Exception) -> JSONResponse:
    """
    Handle custom LLM-related exceptions.
    """
    assert isinstance(exc, LLMBaseError)

    error_context = extract_error_context(exc)

    logger.error(
        "LLM Error: type=%s, category=%s, path=%s, method=%s, message=%s",
        error_context["type"],
        error_context["llm_error_category"],
        request.url.path,
        request.method,
        error_context["message"],
        exc_info=True,
    )

    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "detail": get_user_friendly_error_message(exc),
            "error_type": error_context["llm_error_category"],
        },
    )


async def general_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """
    Handle all uncaught exceptions.

    This is the catch-all handler that ensures no raw exception messages
    are exposed to users. It logs the full error details and returns a
    user-friendly message.
    """
    error_context = extract_error_context(exc)

    # Check if this is an LLM-related error
    is_llm_error = error_context["is_llm_related"]
    error_category = error_context["llm_error_category"]

    # Log the full error for debugging (but never expose to user)
    logger.error(
        "Uncaught Exception: type=%s, is_llm_related=%s, category=%s, path=%s, method=%s",
        error_context["type"],
        is_llm_error,
        error_category,
        request.url.path,
        request.method,
        exc_info=True,
    )

    # For LLM authentication errors, we specifically want to prompt the user
    # to check their API key
    if (
        error_category == "llm_authentication"
        or error_category == "llm_unknown_provider"
    ):
        status_code = status.HTTP_401_UNAUTHORIZED
    elif is_llm_error:
        status_code = status.HTTP_500_INTERNAL_SERVER_ERROR
    else:
        status_code = status.HTTP_500_INTERNAL_SERVER_ERROR

    return JSONResponse(
        status_code=status_code,
        content={
            "detail": get_user_friendly_error_message(exc),
            "error_type": error_category if is_llm_error else "internal_error",
        },
    )


# ==============================================================================
# Handler Registration
# ==============================================================================


def register_exception_handlers(app: FastAPI) -> None:
    """
    Register all exception handlers with the FastAPI application.

    This should be called once during app initialization.
    """
    # Register HTTPException handler
    app.add_exception_handler(
        HTTPException,
        http_exception_handler,  # type: ignore
    )

    # Register custom LLM error handlers
    app.add_exception_handler(
        LLMBaseError,
        llm_base_error_handler,  # type: ignore
    )

    # Register catch-all handler for all other exceptions
    app.add_exception_handler(Exception, general_exception_handler)

    logger.info("Exception handlers registered successfully")


# ==============================================================================
# Utility for SSE Streaming Errors
# ==============================================================================


def format_sse_error(exception: Exception) -> dict[str, Any]:
    """
    Format an exception for SSE streaming responses.

    This function ensures that error messages sent through SSE streaming
    are also user-friendly and don't expose sensitive information.

    Example usage:
        try:
            ...
        except Exception as e:
            error_data = format_sse_error(e)
            yield f"data: {json.dumps(error_data)}\n\n"
    """
    error_context = extract_error_context(exception)

    # Always log the full error
    logger.error(
        "SSE Streaming Error: type=%s, category=%s, message=%s",
        error_context["type"],
        error_context["llm_error_category"],
        error_context["message"],
        exc_info=True,
    )

    return {
        "type": "error",
        "content": get_user_friendly_error_message(exception),
        "error_type": error_context["llm_error_category"]
        if error_context["is_llm_related"]
        else "internal_error",
    }
