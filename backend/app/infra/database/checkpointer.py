"""
PostgreSQL checkpointer backend (LangGraph AsyncPostgresSaver).

Provides short-term memory for LangGraph agents. Saves conversation state
(think of it as "saving the game") so agents can resume from previous turns.

Reference:
https://docs.langchain.com/oss/python/langgraph/persistence#checkpointer-libraries
"""

import logging
from typing import AsyncContextManager

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

from app.infra.config import get_settings
from app.infra.errors import CheckpointerError

logger = logging.getLogger(__name__)


class PostgresCheckpointer:
    """PostgreSQL checkpointer backend using LangGraph AsyncPostgresSaver."""

    def __init__(self) -> None:
        self._saver: AsyncPostgresSaver | None = None
        self._cm: AsyncContextManager[AsyncPostgresSaver] | None = None

    async def initialize(self) -> None:
        """Initialize the checkpointer connection and create tables.

        Uses AsyncPostgresSaver.from_conn_string context manager pattern
        as recommended by LangGraph documentation.
        """
        if self._saver is not None:
            logger.warning("Checkpointer already initialized, skipping")
            return

        settings = get_settings()
        try:
            self._cm = AsyncPostgresSaver.from_conn_string(
                settings.get_postgres_conn_string()
            )
            self._saver = await self._cm.__aenter__()
            await self._saver.setup()
            logger.info("PostgreSQL checkpointer initialized")
        except Exception as e:
            raise CheckpointerError(
                f"Failed to initialize checkpointer: {e}",
                operation="initialize",
            ) from e

    def get_saver(self) -> AsyncPostgresSaver:
        """Return the LangGraph-compatible checkpoint saver."""
        if self._saver is None:
            raise CheckpointerError(
                "Checkpointer not initialized. Call initialize() first.",
                operation="get_saver",
            )
        return self._saver

    async def dispose(self) -> None:
        """Dispose the checkpointer connection.

        Uses graceful cleanup: attempts normal exit first, then forced cleanup
        on any remaining resources. Safe to call multiple times.
        """
        if self._cm is None:
            return

        # Clear references first to prevent reuse during cleanup
        cm = self._cm
        self._saver = None
        self._cm = None

        try:
            await cm.__aexit__(None, None, None)
            logger.info("PostgreSQL checkpointer disposed")
        except Exception as e:
            # Log but don't raise - cleanup should be best-effort
            logger.warning("Error disposing checkpointer (cleanup continued): %s", e)
            # Ensure resources are released even on error
            try:
                # Force cleanup with exception context
                exc_info = (type(e), e, e.__traceback__)
                await cm.__aexit__(*exc_info)
            except Exception:
                pass  # Ignore nested cleanup errors
            finally:
                logger.info("PostgreSQL checkpointer disposed (with cleanup warnings)")
