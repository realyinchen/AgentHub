"""
PostgreSQL checkpointer backend (LangGraph AsyncPostgresSaver).

Provides short-term memory for LangGraph agents. Saves conversation state
(think of it as "saving the game") so agents can resume from previous turns.
"""

from __future__ import annotations

import logging
from typing import (
    AsyncContextManager,
)

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

from app.infra.config import get_settings

logger = logging.getLogger(__name__)


class PostgresCheckpointer:
    """PostgreSQL checkpointer backend using LangGraph AsyncPostgresSaver."""

    def __init__(self) -> None:
        self._saver: AsyncPostgresSaver | None = None
        self._cm: AsyncContextManager[AsyncPostgresSaver] | None = None

    async def initialize(self) -> None:
        if self._saver is not None:
            logger.warning("Checkpointer already initialized, skipping")
            return
        settings = get_settings()
        self._cm = AsyncPostgresSaver.from_conn_string(
            settings.get_postgres_libpq_url()
        )
        self._saver = await self._cm.__aenter__()
        await self._saver.setup()
        logger.info("PostgreSQL checkpointer initialized")

    def get_saver(self) -> AsyncPostgresSaver:
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
                logger.info("PostgreSQL checkpointer disposed")
