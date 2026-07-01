"""Logging utilities — context-aware log enrichment via contextvars.

Provides a ``RequestIdFilter`` that automatically injects ``request_id``,
``user_id``, and ``thread_id`` into every log record within a request context,
removing the need for manual formatting across the codebase.

Usage::

    from app.utils.logging import request_id_context, user_id_context, thread_id_context, RequestIdFilter

    # In request handler / middleware:
    token = request_id_context.set("req-abc-123")
    try:
        ...
    finally:
        request_id_context.reset(token)

    # In main.py logging configuration:
    root_logger.addFilter(RequestIdFilter())
"""

import contextvars
import json
import logging
import os
import re
from datetime import datetime, timezone
from typing import Any

# ── Startup guard ────────────────────────────────────────────────────────────
# During application startup, no request context exists yet.  INFO/DEBUG logs
# from startup (e.g. "System LLM initialized") would be dropped by
# RequestIdFilter.  This flag prevents that — the filter only starts dropping
# no-context logs after startup is complete.

_startup_complete: bool = False


def mark_startup_complete() -> None:
    """Signal that application startup is finished.

    After this is called, RequestIdFilter will begin dropping INFO/DEBUG
    records that have no request context (all context IDs are ``-``).
    """
    global _startup_complete
    _startup_complete = True

# ── Context variables ────────────────────────────────────────────────────────
# Each asyncio task inherits its parent's context, so sub-tasks spawned
# within a request handler automatically see the same values.

_request_id_ctx: contextvars.ContextVar[str] = contextvars.ContextVar(
    "request_id", default="-"
)
_user_id_ctx: contextvars.ContextVar[str] = contextvars.ContextVar(
    "user_id", default="-"
)
_thread_id_ctx: contextvars.ContextVar[str] = contextvars.ContextVar(
    "thread_id", default="-"
)


def _make_context_class(name: str, ctx_var: contextvars.ContextVar[str]) -> type:
    """Factory for lightweight context-variable wrapper classes."""

    class _Context:
        @staticmethod
        def set(value: str) -> contextvars.Token:
            return ctx_var.set(value)

        @staticmethod
        def get() -> str:
            return ctx_var.get()

        @staticmethod
        def reset(token: contextvars.Token) -> None:
            ctx_var.reset(token)

    _Context.__name__ = name
    _Context.__qualname__ = name
    return _Context


RequestIdContext = _make_context_class("RequestIdContext", _request_id_ctx)
UserIdContext = _make_context_class("UserIdContext", _user_id_ctx)
ThreadIdContext = _make_context_class("ThreadIdContext", _thread_id_ctx)

# Module-level convenience aliases
request_id_context = RequestIdContext()
user_id_context = UserIdContext()
thread_id_context = ThreadIdContext()


class RequestIdFilter(logging.Filter):
    """Logging filter that injects ``request_id``, ``user_id``, and ``thread_id``
    into every log record.

    After registration on the root logger (or any logger), every
    ``logging.info(...)`` call automatically includes these fields
    in the record — no manual formatting needed.

    **Filtering behavior**: When all three context IDs are ``-`` (i.e. no request
    context is active), INFO and DEBUG records are silently dropped.  WARNING
    and above are always emitted so that errors during startup / background
    tasks are never lost.

    Registration in ``main.py``::

        import logging
        from app.utils.logging import RequestIdFilter

        root = logging.getLogger()
        root.addFilter(RequestIdFilter())
    """

    def filter(self, record: logging.LogRecord) -> bool:
        request_id = request_id_context.get()
        user_id = user_id_context.get()
        thread_id = thread_id_context.get()

        record.request_id = request_id
        record.user_id = user_id
        record.thread_id = thread_id

        # During startup, allow all logs through (no request context exists yet).
        if not _startup_complete:
            return True

        # Drop INFO/DEBUG logs that have no request context (all IDs are "-").
        # WARNING and above are always kept so errors during startup / background
        # tasks are never silently lost.
        if (
            record.levelno < logging.WARNING
            and request_id == "-"
            and user_id == "-"
            and thread_id == "-"
        ):
            return False

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
            "user_id": "550e8400-...",
            "thread_id": "conv-xyz-789",
            "request_id": "req-abc-123",
            "code_file_path": "[chat.py]",
            "message": "Starting stream with model=..."
        }

    When ``exc_info`` is present, an ``exception`` field with the traceback
    string is appended.

    Usage::

        handler.setFormatter(JsonFormatter())
    """

    # Base directory for computing relative paths in log output.
    # We walk up from this file (app/utils/logging.py) to find the backend root.
    _backend_root: str = os.path.dirname(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    )

    def format(self, record: logging.LogRecord) -> str:
        if record.pathname:
            try:
                rel = os.path.relpath(record.pathname, self._backend_root)
            except ValueError:
                rel = record.pathname
        else:
            rel = "-"
        log_entry: dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "user_id": getattr(record, "user_id", "-"),
            "thread_id": getattr(record, "thread_id", "-"),
            "request_id": getattr(record, "request_id", "-"),
            "code_file_path": f"[{rel}]",
            "message": record.getMessage(),
        }

        if record.exc_info and record.exc_info[1] is not None:
            log_entry["exception"] = self.formatException(record.exc_info)

        return json.dumps(log_entry, ensure_ascii=False, default=str)


# =============================================================================
# Colored Log Formatter — ANSI color codes for log levels
# =============================================================================

_COLOR_RESET = "\033[0m"

_LEVEL_COLORS: dict[int, str] = {
    logging.DEBUG: "\033[34m",       # Blue
    logging.INFO: "\033[32m",        # Green
    logging.WARNING: "\033[33m",     # Yellow
    logging.ERROR: "\033[31m",       # Red
    logging.CRITICAL: "\033[1;31m",  # Bold Red
}


# Pattern to strip placeholder context IDs from formatted output
# Matches "user_id=- thread_id=- request_id=- " (with trailing space)
_NO_CONTEXT_RE = re.compile(r"user_id=-\s+thread_id=-\s+request_id=-\s+")

class ColoredFormatter(logging.Formatter):
    """Formatter that wraps the log level name in ANSI color codes.

    When all three context IDs (user_id, thread_id, request_id) are ``-``,
    they are omitted from the output to reduce noise during startup.

    Usage::

        handler.setFormatter(ColoredFormatter(
            "%(asctime)s %(levelname)s [%(pathname)s:%(lineno)d] %(message)s"
        ))
    """

    def format(self, record: logging.LogRecord) -> str:
        color = _LEVEL_COLORS.get(record.levelno, "")
        if color:
            record.levelname = f"{color}{record.levelname}{_COLOR_RESET}"
        result = super().format(record)
        # Strip placeholder IDs when no request context is active
        if (
            getattr(record, "user_id", "-") == "-"
            and getattr(record, "thread_id", "-") == "-"
            and getattr(record, "request_id", "-") == "-"
        ):
            result = _NO_CONTEXT_RE.sub("", result)
        return result
