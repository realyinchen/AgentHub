"""
SQLite Checkpointer Backend

Implements CheckpointInterface using LangGraph's AsyncSqliteSaver.
Mirrors the PostgresCheckpointer structure for consistency.
"""

import logging
from pathlib import Path
from typing import AsyncContextManager

from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from app.core.config import settings
from app.database.interfaces import CheckpointInterface

logger = logging.getLogger(__name__)


class SqliteCheckpointer(CheckpointInterface):
    """SQLite checkpointer backend using LangGraph AsyncSqliteSaver."""

    def __init__(self) -> None:
        self._saver: AsyncSqliteSaver | None = None
        self._cm: AsyncContextManager[AsyncSqliteSaver] | None = None

    async def initialize(self) -> None:
        """Initialize the AsyncSqliteSaver and create checkpoint tables."""
        if self._saver is not None:
            logger.warning("Checkpointer already initialized, skipping")
            return

        # Ensure the database directory exists
        db_path = Path(settings.SQLITE_DATABASE_PATH)
        db_path.parent.mkdir(parents=True, exist_ok=True)

        # from_conn_string returns an async context manager that yields AsyncSqliteSaver
        self._cm = AsyncSqliteSaver.from_conn_string(settings.SQLITE_DATABASE_PATH)
        self._saver = await self._cm.__aenter__()
        await self._saver.setup()
        logger.info(
            f"SQLite checkpointer initialized at {settings.SQLITE_DATABASE_PATH}"
        )

    def get_saver(self) -> AsyncSqliteSaver:
        """Return the LangGraph-compatible AsyncSqliteSaver instance."""
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
                logger.info("SQLite checkpointer disposed")