"""Stable error vocabulary shared by embedding probes and runtime routing."""

from __future__ import annotations

from typing import Literal


EmbeddingErrorCategory = Literal[
    "network",
    "auth",
    "model",
    "rate_limit",
    "dimension",
    "provider",
]


class EmbeddingDimensionError(ValueError):
    """Raised when an embedding response has an invalid vector shape."""


def classify_embedding_error(exc: Exception) -> EmbeddingErrorCategory:
    """Map provider-specific failures into a transport-neutral category."""

    if isinstance(exc, EmbeddingDimensionError):
        return "dimension"

    class_name = type(exc).__name__.lower()
    message = (str(exc) or class_name).lower()
    status_code = _status_code(exc)

    if status_code == 429 or _contains(
        class_name,
        message,
        "ratelimit",
        "rate limit",
        "too many requests",
        "quota exceeded",
    ):
        return "rate_limit"
    if status_code in {401, 403} or _contains(
        class_name,
        message,
        "authentication",
        "permissiondenied",
        "unauthorized",
        "forbidden",
        "invalid api key",
        "incorrect api key",
    ):
        return "auth"
    if _contains(
        class_name,
        message,
        "dimension",
        "empty vector",
        "non-array vector",
        "non-finite",
        "different number of vectors",
    ):
        return "dimension"
    if _contains(
        class_name,
        message,
        "apiconnection",
        "connectionerror",
        "connecterror",
        "networkerror",
        "timeouterror",
        "timeout",
        "connection error",
        "connection refused",
        "name resolution",
        "dns",
    ):
        return "network"
    if status_code == 404 or _contains(
        class_name,
        message,
        "notfound",
        "model not found",
        "model does not exist",
        "unknown model",
        "unsupported model",
        "does not support embedding",
        "does not support embeddings",
        "no endpoints found",
    ):
        return "model"
    return "provider"


def safe_embedding_error(exc: Exception, *, limit: int = 1000) -> str:
    message = str(exc) or exc.__class__.__name__
    if len(message) > limit:
        return f"{message[: limit - 3]}..."
    return message


def _status_code(exc: Exception) -> int | None:
    for source in (exc, getattr(exc, "response", None)):
        value = getattr(source, "status_code", None)
        try:
            if value is not None:
                return int(value)
        except (TypeError, ValueError):
            continue
    return None


def _contains(class_name: str, message: str, *needles: str) -> bool:
    return any(needle in class_name or needle in message for needle in needles)


__all__ = [
    "EmbeddingDimensionError",
    "EmbeddingErrorCategory",
    "classify_embedding_error",
    "safe_embedding_error",
]
