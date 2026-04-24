"""
PostgreSQL Database Backend

Implements DatabaseInterface using SQLAlchemy async engine + async session.
"""

import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import settings
from app.database.interfaces import DatabaseInterface

logger = logging.getLogger(__name__)


class PostgresDatabase(DatabaseInterface):
    """PostgreSQL database backend using SQLAlchemy async."""

    def __init__(self) -> None:
        self._engine: AsyncEngine | None = None
        self._session_factory: async_sessionmaker[AsyncSession] | None = None

    @property
    def engine(self) -> AsyncEngine:
        """Get the async engine, raising if not initialized."""
        if self._engine is None:
            raise RuntimeError("Database not initialized. Call initialize() first.")
        return self._engine

    def _build_database_url(self) -> str:
        """Build the SQLAlchemy async connection URL from settings."""
        if settings.POSTGRES_PASSWORD is None:
            raise ValueError("POSTGRES_PASSWORD is not set")
        return (
            f"postgresql+asyncpg://{settings.POSTGRES_USER}:{settings.POSTGRES_PASSWORD.get_secret_value()}"
            f"@{settings.POSTGRES_HOST}:{settings.POSTGRES_PORT}/{settings.POSTGRES_DB}"
        )

    def _create_engine(self) -> AsyncEngine:
        """Create the async engine with connection pool settings."""
        url = self._build_database_url()
        return create_async_engine(
            url,
            echo=False,
            pool_size=5,
            max_overflow=10,
            pool_timeout=30,
            pool_recycle=3600,
            pool_pre_ping=True,
        )

    async def initialize(self) -> None:
        """Initialize the async engine and session factory."""
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
        """
        Yield an async database session.

        Commits on success, rolls back on exception.
        This provides auto-commit semantics as a safety net:
        even if a caller forgets to commit, data will still be persisted.
        """
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

    async def execute_query(self, query, params=None):
        """Execute a raw SQL query and return results."""
        async with self.session() as session:
            result = await session.execute(query, params or {})
            return result

    async def dispose(self) -> None:
        """Dispose of the async engine and all connections."""
        if self._engine is not None:
            await self._engine.dispose()
            self._engine = None
            self._session_factory = None
            logger.info("PostgreSQL database engine disposed")
