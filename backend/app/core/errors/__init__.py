"""
Error handling module.

This module contains custom exception types and exception handlers
for centralized error handling in the FastAPI application.
"""

from app.core.errors.exceptions import (
    LLMBaseError,
    LLMAuthenticationError,
    LLMConnectionError,
    LLMInvalidRequestError,
    LLMRateLimitError,
    LLMPermissionError,
    LLMUnknownProviderError,
    is_llm_authentication_error,
    is_llm_connection_error,
    is_llm_rate_limit_error,
    is_llm_invalid_request_error,
    is_llm_unknown_provider_error,
    is_llm_related_error,
    classify_llm_error,
    get_user_friendly_error_message,
    should_show_detailed_error,
    extract_error_context,
)

from app.core.errors.exception_handlers import (
    http_exception_handler,
    llm_base_error_handler,
    general_exception_handler,
    register_exception_handlers,
    format_sse_error,
)

__all__ = [
    # Exceptions
    "LLMBaseError",
    "LLMAuthenticationError",
    "LLMConnectionError",
    "LLMInvalidRequestError",
    "LLMRateLimitError",
    "LLMPermissionError",
    "LLMUnknownProviderError",
    # Error detection
    "is_llm_authentication_error",
    "is_llm_connection_error",
    "is_llm_rate_limit_error",
    "is_llm_invalid_request_error",
    "is_llm_unknown_provider_error",
    "is_llm_related_error",
    "classify_llm_error",
    # Error messages
    "get_user_friendly_error_message",
    "should_show_detailed_error",
    "extract_error_context",
    # Exception handlers
    "http_exception_handler",
    "llm_base_error_handler",
    "general_exception_handler",
    "register_exception_handlers",
    "format_sse_error",
]
