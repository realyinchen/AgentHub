"""
SQLite checkpointer backend (LangGraph AsyncSqliteSaver).

Provides short-term memory for LangGraph agents (development / testing).
Saves conversation state so agents can resume from previous turns.
For dev mode only; production uses postgres/checkpointer.py.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import AsyncContextManager

from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from app.infra.config import get_settings

logger = logging.getLogger(__name__)


class SqliteCheckpointer:
    """SQLite checkpointer backend using LangGraph AsyncSqliteSaver."""

    def __init__(self) -> None:
        self._saver: AsyncSqliteSaver | None = None
        self._cm: AsyncContextManager[AsyncSqliteSaver] | None = None

    async def initialize(self) -> None:
        if self._saver is not None:
            logger.warning("Checkpointer already initialized, skipping")
            return

        settings = get_settings()
        Path(settings.SQLITE_DATABASE_PATH).parent.mkdir(parents=True, exist_ok=True)

        self._cm = AsyncSqliteSaver.from_conn_string(settings.SQLITE_DATABASE_PATH)
        self._saver = await self._cm.__aenter__()
        await self._saver.setup()
        logger.info(
            "SQLite checkpointer initialized at %s", settings.SQLITE_DATABASE_PATH
        )

    def get_saver(self) -> AsyncSqliteSaver:
        if self._saver is None:
            raise RuntimeError("Checkpointer not initialized. Call initialize() first.")
        return self._saver

    async def dispose(self) -> None:
        if self._cm is not None:
            try:
                await self._cm.__aexit__(None, None, None)
            except Exception as e:
                logger.warning("Error disposing checkpointer: %s", e)
            finally:
                self._saver = None
                self._cm = None
                logger.info("SQLite checkpointer disposed")
