import asyncio
import logging
import os
import sys
import warnings
import uvicorn
from dotenv import load_dotenv

from app.infra.config import get_settings
from app.utils.logging import JsonFormatter, RequestIdFilter

# ─────────────────────────────────────────────────────────────────────────────
# Suppress third-party warnings BEFORE any imports that might trigger them
# ─────────────────────────────────────────────────────────────────────────────

# Suppress Pydantic serialization warnings from LiteLLM
# These are benign type hints that don't affect functionality
warnings.filterwarnings("ignore", category=UserWarning, module="pydantic")

# Suppress LiteLLM INFO/WARNING logs (keep only ERROR)
# Must be set before litellm is imported anywhere in the application
logging.getLogger("litellm").setLevel(logging.ERROR)

# ─────────────────────────────────────────────────────────────────────────────

# Set Compatible event loop policy on Windows Systems.
# On Windows systems, the default ProactorEventLoop can cause issues with
# certain async database drivers like psycopg (PostgreSQL driver).
# The WindowsSelectorEventLoopPolicy provides better compatibility and prevents
# "RuntimeError: Event loop is closed" errors when working with database connections.
# This MUST be set before any async operations, including module imports that may
# create event loops (especially important for uvicorn --reload mode where child
# processes re-import modules but don't run __main__ block).
# Refer to the documentation for more information.
# https://www.psycopg.org/psycopg3/docs/advanced/async.html#asynchronous-operations
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

# Load environment variables first
load_dotenv()

settings = get_settings()


def _reload_enabled() -> bool:
    """Allow local dev to disable uvicorn reload without switching MODE=prod."""
    raw = os.getenv("UVICORN_RELOAD")
    if raw is None:
        return settings.is_dev
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def create_event_loop() -> asyncio.AbstractEventLoop:
    """Create a psycopg-compatible event loop on Windows."""
    if sys.platform == "win32":
        return asyncio.SelectorEventLoop()
    return asyncio.new_event_loop()


def configure_logging() -> None:
    """Configure application-wide logging.

    Two formats are supported, controlled by ``LOG_FORMAT``:

    - ``console`` (default for dev): Human-readable with timestamp, logger
      name, request_id, and message.
    - ``json`` (recommended for prod): One JSON object per line, compatible
      with log aggregation systems (ELK, Loki, Datadog, etc.). Uses only
      stdlib ``json`` — no external dependencies.

    Both formats automatically include ``request_id`` via the
    ``RequestIdFilter`` registered in ``app.main``.

    Third-party library noise is suppressed (httpcore, httpx, langchain,
    langgraph) regardless of format.
    """
    root = logging.getLogger()
    root.setLevel(settings.LOG_LEVEL)

    # Remove any pre-existing handlers (basicConfig adds a StreamHandler)
    root.handlers.clear()

    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(settings.LOG_LEVEL)

    # Register RequestIdFilter on the handler so %(request_id)s works
    # in format strings. Filters must be on handlers, not loggers,
    # because child-logger records propagate to parent handlers but
    # NOT through parent logger filters.
    handler.addFilter(RequestIdFilter())

    if settings.LOG_FORMAT == "json":
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)-8s [%(name)s] %(message)s")
        )

    root.addHandler(handler)

    # Set app logger level
    logging.getLogger("app").setLevel(settings.LOG_LEVEL)

    # Suppress noisy third-party libraries
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("langchain").setLevel(logging.WARNING)
    logging.getLogger("langgraph").setLevel(logging.WARNING)


if __name__ == "__main__":
    # Configure logging before importing app modules so all loggers
    # inherit the correct format.
    configure_logging()

    # Note: Windows event loop policy is set at module level (see top of file)
    # to ensure it applies in uvicorn --reload mode where child processes
    # re-import modules but don't run this __main__ block.

    reload = _reload_enabled()
    uvicorn.run(
        "app.main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=reload,
        reload_dirs=["app"] if reload else None,
        loop="run_backend:create_event_loop",
        timeout_graceful_shutdown=settings.GRACEFUL_SHUTDOWN_TIMEOUT,
    )
