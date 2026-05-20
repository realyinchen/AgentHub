"""
PostgreSQL database backend (SQLAlchemy + asyncpg).

Provides the relational database layer for storing user data, conversation history,
and model configurations.
"""

from __future__ import annotations

import json
import logging
from contextlib import asynccontextmanager
from typing import (
    Any,
    AsyncGenerator,
    Optional,
)

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.infra.config import get_settings

logger = logging.getLogger(__name__)


def _json_serializer(obj: Any) -> str:
    """JSON serializer that preserves Unicode characters (ensure_ascii=False)."""
    return json.dumps(obj, ensure_ascii=False, default=str)


class PostgresDatabase:
    """PostgreSQL database backend using SQLAlchemy async."""

    def __init__(self) -> None:
        self._engine: AsyncEngine | None = None
        self._session_factory: async_sessionmaker[AsyncSession] | None = None

    @property
    def engine(self) -> AsyncEngine:
        if self._engine is None:
            raise RuntimeError("Database not initialized. Call initialize() first.")
        return self._engine

    def _create_engine(self) -> AsyncEngine:
        settings = get_settings()
        pool_size = settings.POSTGRES_MIN_CONNECTIONS_PER_POOL
        max_overflow = max(
            0,
            settings.POSTGRES_MAX_CONNECTIONS_PER_POOL
            - settings.POSTGRES_MIN_CONNECTIONS_PER_POOL,
        )
        return create_async_engine(
            settings.get_async_postgres_url(),
            echo=False,
            pool_size=pool_size,
            max_overflow=max_overflow,
            pool_timeout=30,
            pool_recycle=3600,
            pool_pre_ping=True,
            json_serializer=_json_serializer,
        )

    async def initialize(self) -> None:
        if self._engine is not None:
            logger.warning("Database already initialized, skipping")
            return
        self._engine = self._create_engine()
        self._session_factory = async_sessionmaker(
            self._engine,
            class_=AsyncSession,
            expire_on_commit=False,
        )
        logger.info("PostgreSQL database engine initialized")

    @asynccontextmanager
    async def session(self) -> AsyncGenerator[AsyncSession, None]:
        """Yield an async session with auto-commit/rollback semantics."""
        if self._session_factory is None:
            raise RuntimeError("Database not initialized. Call initialize() first.")
        session = self._session_factory()
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()

    async def execute_query(self, query: Any, params: Optional[dict] = None) -> Any:
        async with self.session() as session:
            return await session.execute(query, params or {})

    async def dispose(self) -> None:
        if self._engine is not None:
            await self._engine.dispose()
            self._engine = None
            self._session_factory = None
            logger.info("PostgreSQL database engine disposed")


# Type alias for type-checking. LangGraph's Store also uses the same
# libpq connection string, so we can reuse the same settings.
PostgresStoreDatabase = PostgresDatabase
