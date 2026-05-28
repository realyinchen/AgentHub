"""Logging utilities — context-aware log enrichment via contextvars.

Provides a ``RequestIdFilter`` that automatically injects ``request_id``
into every log record within a request context, removing the need for
manual ``[request_id=%s]`` formatting across the codebase.

Usage::

    from app.utils.logging import request_id_context, RequestIdFilter

    # In request handler / middleware:
    token = request_id_context.set("req-abc-123")
    try:
        ...
    finally:
        request_id_context.reset(token)

    # In main.py logging configuration:
    root_logger.addFilter(RequestIdFilter())
"""

from __future__ import annotations

import contextvars
import json
import logging
from datetime import datetime, timezone
from typing import Any

# Context variable that lives for the duration of a single request.
# Each asyncio task inherits its parent's context, so sub-tasks spawned
# within a request handler automatically see the same request_id.
_request_id_ctx: contextvars.ContextVar[str] = contextvars.ContextVar(
    "request_id", default="-"
)


class RequestIdContext:
    """Convenience wrapper around the ``request_id`` context variable.

    Provides a ``set()`` method that returns an opaque token suitable for
    ``reset()``, matching the ``contextvars`` pattern::

        token = request_id_context.set("req-abc-123")
        try:
            ...
        finally:
            request_id_context.reset(token)
    """

    @staticmethod
    def set(request_id: str) -> contextvars.Token:
        """Set the current request_id and return a reset token."""
        return _request_id_ctx.set(request_id)

    @staticmethod
    def get() -> str:
        """Get the current request_id (returns "-" if not set)."""
        return _request_id_ctx.get()

    @staticmethod
    def reset(token: contextvars.Token) -> None:
        """Reset the context variable to its previous value."""
        _request_id_ctx.reset(token)


# Module-level convenience alias
request_id_context = RequestIdContext()


class RequestIdFilter(logging.Filter):
    """Logging filter that injects ``request_id`` into every log record.

    After registration on the root logger (or any logger), every
    ``logging.info(...)`` call automatically includes ``request_id``
    in the record — no manual formatting needed.

    Registration in ``main.py``::

        import logging
        from app.utils.logging import RequestIdFilter

        root = logging.getLogger()
        root.addFilter(RequestIdFilter())
    """

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_context.get()  # type: ignore[attr-defined]
        return True


def get_request_id() -> str:
    """Return the current request_id (convenience function).

    Returns "-" when called outside of a request context.
    """
    return request_id_context.get()


# =============================================================================
# Context Manager (optional — for use outside of request_handler.py)
# =============================================================================


class request_id_scope:
    """Context manager that sets request_id for the duration of a block.

    Usage::

        with request_id_scope("req-abc-123"):
            logger.info("This log has request_id=req-abc-123")
    """

    def __init__(self, request_id: str) -> None:
        self._request_id = request_id
        self._token: contextvars.Token | None = None

    def __enter__(self) -> "request_id_scope":
        self._token = request_id_context.set(self._request_id)
        return self

    def __exit__(self, *args: Any) -> None:
        if self._token is not None:
            request_id_context.reset(self._token)
        return None


# =============================================================================
# JSON Log Formatter (stdlib only — no external dependency)
# =============================================================================


class JsonFormatter(logging.Formatter):
    """Standard-library-based JSON log formatter.

    Outputs one JSON object per line with these fields::

        {
            "timestamp": "2026-05-27T12:34:56.789Z",
            "level": "INFO",
            "logger": "app.api.v1.chat",
            "request_id": "req-abc-123",
            "message": "build_agent_kwargs: thread_id=..."
        }

    When ``exc_info`` is present, an ``exception`` field with the traceback
    string is appended.

    Usage::

        handler.setFormatter(JsonFormatter())
    """

    def format(self, record: logging.LogRecord) -> str:
        log_entry: dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "request_id": getattr(record, "request_id", "-"),
            "message": record.getMessage(),
        }

        if record.exc_info and record.exc_info[1] is not None:
            log_entry["exception"] = self.formatException(record.exc_info)

        return json.dumps(log_entry, ensure_ascii=False, default=str)
