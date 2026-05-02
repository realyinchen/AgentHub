"""
Custom exception types and error handling utilities.

This module defines custom exceptions and utility functions for detecting
and classifying different types of errors, particularly LLM-related errors.
"""

import logging
from typing import Any


logger = logging.getLogger(__name__)


# ==============================================================================
# Custom Exception Types
# ==============================================================================


class LLMBaseError(Exception):
    """Base exception for LLM-related errors."""

    pass


class LLMAuthenticationError(LLMBaseError):
    """Raised when LLM API key is invalid or authentication fails."""

    pass


class LLMConnectionError(LLMBaseError):
    """Raised when there's a network/connection issue with LLM provider."""

    pass


class LLMInvalidRequestError(LLMBaseError):
    """Raised when the request to LLM is invalid (bad parameters, etc.)."""

    pass


class LLMRateLimitError(LLMBaseError):
    """Raised when LLM API rate limit is exceeded."""

    pass


class LLMPermissionError(LLMBaseError):
    """Raised when LLM API permission is denied (e.g., model not accessible)."""

    pass


class LLMUnknownProviderError(LLMBaseError):
    """Raised when the model provider is unknown or not supported."""

    pass


# ==============================================================================
# Error Detection Utilities
# ==============================================================================


def is_llm_authentication_error(exception: Exception) -> bool:
    """
    Detect if an exception is related to LLM authentication/API key issues.
    """
    error_str = str(exception).lower()
    class_name = type(exception).__name__.lower()

    auth_keywords = [
        "auth",
        "api key",
        "api_key",
        "authentication",
        "unauthorized",
        "401",
        "forbidden",
        "403",
        "invalid",
        "incorrect",
        "wrong key",
        "missing key",
    ]

    # Check exception type name
    auth_type_names = [
        "authenticationerror",
        "autherror",
        "unauthorizederror",
    ]

    if any(keyword in class_name for keyword in auth_type_names):
        return True

    # Check error message content
    if any(keyword in error_str for keyword in auth_keywords):
        return True

    return False


def is_llm_connection_error(exception: Exception) -> bool:
    """
    Detect if an exception is related to LLM connection/network issues.
    """
    error_str = str(exception).lower()
    class_name = type(exception).__name__.lower()

    connection_keywords = [
        "connection",
        "timeout",
        "network",
        "socket",
        "dns",
        "could not connect",
        "failed to connect",
        "connection refused",
        "connection reset",
        "econnrefused",
        "etimedout",
        "502",
        "503",
        "504",
        "bad gateway",
        "service unavailable",
        "gateway timeout",
    ]

    connection_type_names = [
        "apiconnectionerror",
        "connectionerror",
        "timeouterror",
        "networkerror",
    ]

    if any(keyword in class_name for keyword in connection_type_names):
        return True

    if any(keyword in error_str for keyword in connection_keywords):
        return True

    return False


def is_llm_rate_limit_error(exception: Exception) -> bool:
    """
    Detect if an exception is related to LLM rate limiting.
    """
    error_str = str(exception).lower()
    class_name = type(exception).__name__.lower()

    rate_limit_keywords = [
        "rate limit",
        "ratelimit",
        "quota",
        "too many requests",
        "429",
        "rate exceeded",
        "request limit",
    ]

    rate_limit_type_names = [
        "ratelimiterror",
        "toolmanyrequests",
        "quotaexceedederror",
    ]

    if any(keyword in class_name for keyword in rate_limit_type_names):
        return True

    if any(keyword in error_str for keyword in rate_limit_keywords):
        return True

    return False


def is_llm_invalid_request_error(exception: Exception) -> bool:
    """
    Detect if an exception is related to invalid LLM request parameters.
    """
    error_str = str(exception).lower()
    class_name = type(exception).__name__.lower()

    invalid_request_keywords = [
        "invalid request",
        "bad request",
        "400",
        "parameter",
        "invalid parameter",
        "missing parameter",
        "max tokens",
        "context length",
        "contextwindow",
        "maximum context",
    ]

    invalid_request_type_names = [
        "invalidrequesterror",
        "badrequesterror",
        "validationerror",
    ]

    if any(keyword in class_name for keyword in invalid_request_type_names):
        return True

    if any(keyword in error_str for keyword in invalid_request_keywords):
        return True

    return False


def is_llm_unknown_provider_error(exception: Exception) -> bool:
    """
    Detect if an exception is related to unknown/unsupported model provider.
    """
    error_str = str(exception).lower()
    class_name = type(exception).__name__.lower()

    provider_keywords = [
        "unknown provider",
        "provider not found",
        "invalid provider",
        "unsupported provider",
        "model not found",
        "model does not exist",
        "no such model",
    ]

    provider_type_names = [
        "unknownprovidererror",
        "notimplementederror",
        "notfounderror",
    ]

    if any(keyword in class_name for keyword in provider_type_names):
        return True

    if any(keyword in error_str for keyword in provider_keywords):
        return True

    return False


def is_llm_related_error(exception: Exception) -> bool:
    """
    Detect if an exception is likely related to LLM API calls.
    """
    return (
        is_llm_authentication_error(exception)
        or is_llm_connection_error(exception)
        or is_llm_rate_limit_error(exception)
        or is_llm_invalid_request_error(exception)
        or is_llm_unknown_provider_error(exception)
    )


def classify_llm_error(exception: Exception) -> str:
    """
    Classify an LLM-related error into a category.

    Returns:
        str: Error category:
            - "llm_authentication" (API key issues)
            - "llm_connection" (network issues)
            - "llm_rate_limit" (rate limiting)
            - "llm_invalid_request" (invalid parameters)
            - "llm_unknown_provider" (unknown provider)
            - "unknown" (not classified)
    """
    if is_llm_authentication_error(exception):
        return "llm_authentication"
    elif is_llm_unknown_provider_error(exception):
        return "llm_unknown_provider"
    elif is_llm_connection_error(exception):
        return "llm_connection"
    elif is_llm_rate_limit_error(exception):
        return "llm_rate_limit"
    elif is_llm_invalid_request_error(exception):
        return "llm_invalid_request"
    else:
        return "unknown"


# ==============================================================================
# User-facing Error Messages
# ==============================================================================


def get_user_friendly_error_message(exception: Exception) -> str:
    """
    Get a user-friendly error message for the given exception.

    For LLM authentication/connection/unknown_provider errors, returns a message
    prompting the user to check their API key. For other errors, returns a
    generic internal error message.
    """
    error_category = classify_llm_error(exception)

    # All LLM-related errors that could be API key issues show the same message
    if error_category in [
        "llm_authentication",
        "llm_connection",
        "llm_unknown_provider",
    ]:
        return "Please check if your model API key is valid"
    else:
        # All other errors show generic internal error message
        return "An internal error occurred"


def should_show_detailed_error(exception: Exception) -> bool:
    """
    Determine if detailed error information should be shown to the user.

    Only business logic errors (like validation errors) should show details.
    Internal/LLM errors should be masked.
    """
    from fastapi import HTTPException

    if isinstance(exception, HTTPException):
        # HTTPExceptions are explicitly raised by business logic
        # These are usually safe to show to users
        return True

    return False


# ==============================================================================
# Error Context Extraction
# ==============================================================================


def extract_error_context(exception: Exception) -> dict[str, Any]:
    """
    Extract contextual information from an exception for logging.

    Returns a dictionary with structured information about the error.
    """
    error_context = {
        "type": type(exception).__name__,
        "message": str(exception),
        "is_llm_related": is_llm_related_error(exception),
        "llm_error_category": classify_llm_error(exception),
        "user_message": get_user_friendly_error_message(exception),
    }

    # Try to extract more context if available
    if hasattr(exception, "__dict__"):
        extra_attrs = {}
        for key, value in exception.__dict__.items():
            if not key.startswith("_") and key not in ["args", "message"]:
                try:
                    extra_attrs[key] = str(value)
                except Exception:
                    pass
        if extra_attrs:
            error_context["attributes"] = extra_attrs

    return error_context
