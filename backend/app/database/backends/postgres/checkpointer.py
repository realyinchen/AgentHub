"""
PostgreSQL Checkpointer Backend

Implements CheckpointInterface using LangGraph's AsyncPostgresSaver.
"""

import logging
from typing import AsyncContextManager

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

from app.core.config import settings
from app.database.interfaces import CheckpointInterface

logger = logging.getLogger(__name__)


class PostgresCheckpointer(CheckpointInterface):
    """PostgreSQL checkpointer backend using LangGraph AsyncPostgresSaver."""

    def __init__(self) -> None:
        self._saver: AsyncPostgresSaver | None = None
        self._cm: AsyncContextManager[AsyncPostgresSaver] | None = None

    async def initialize(self) -> None:
        """Initialize the AsyncPostgresSaver and create checkpoint tables."""
        if self._saver is not None:
            logger.warning("Checkpointer already initialized, skipping")
            return

        from urllib.parse import quote_plus

        if settings.POSTGRES_PASSWORD is None:
            raise ValueError("POSTGRES_PASSWORD is not set")

        conn_string = (
            f"postgresql://{settings.POSTGRES_USER}:{quote_plus(settings.POSTGRES_PASSWORD.get_secret_value())}"
            f"@{settings.POSTGRES_HOST}:{settings.POSTGRES_PORT}/{settings.POSTGRES_DB}"
        )

        # from_conn_string returns an async context manager that yields AsyncPostgresSaver
        self._cm = AsyncPostgresSaver.from_conn_string(conn_string)
        self._saver = await self._cm.__aenter__()
        await self._saver.setup()
        logger.info("PostgreSQL checkpointer initialized")

    def get_saver(self) -> AsyncPostgresSaver:
        """Return the LangGraph-compatible AsyncPostgresSaver instance."""
        if self._saver is None:
            raise RuntimeError("Checkpointer not initialized. Call initialize() first.")
        return self._saver

    async def dispose(self) -> None:
        """Dispose of the checkpointer and release connections."""
        if self._cm is not None:
            try:
                await self._cm.__aexit__(None, None, None)
            except Exception as e:
                logger.warning(f"Error disposing checkpointer: {e}")
            finally:
                self._saver = None
                self._cm = None
                logger.info("PostgreSQL checkpointer disposed")
