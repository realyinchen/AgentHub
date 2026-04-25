"""
SQLite Database Backend

Implements DatabaseInterface using SQLAlchemy async engine + aiosqlite.
Mirrors the PostgresDatabase structure for consistency.
"""

import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import StaticPool

from app.core.config import settings
from app.database.interfaces import DatabaseInterface

logger = logging.getLogger(__name__)


class SQLiteDatabase(DatabaseInterface):
    """SQLite database backend using SQLAlchemy async + aiosqlite."""

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
        """Build the SQLAlchemy async connection URL for SQLite."""
        db_path = settings.SQLITE_DATABASE_PATH
        return f"sqlite+aiosqlite:///{db_path}"

    def _ensure_directory_exists(self) -> None:
        """Ensure the directory for the SQLite database file exists."""
        db_path = Path(settings.SQLITE_DATABASE_PATH)
        db_path.parent.mkdir(parents=True, exist_ok=True)

    def _create_engine(self) -> AsyncEngine:
        """Create the async engine with SQLite-compatible settings."""
        url = self._build_database_url()
        return create_async_engine(
            url,
            echo=False,
            # SQLite requires StaticPool for async usage with aiosqlite
            # to avoid "database is locked" errors under concurrent access
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )

    async def initialize(self) -> None:
        """Initialize the async engine, session factory, and create tables."""
        if self._engine is not None:
            logger.warning("Database already initialized, skipping")
            return

        self._ensure_directory_exists()

        self._engine = self._create_engine()
        self._session_factory = async_sessionmaker(
            self._engine,
            class_=AsyncSession,
            expire_on_commit=False,
        )

        # Create all tables from ORM models
        await self._create_tables()

        logger.info(
            f"SQLite database engine initialized at {settings.SQLITE_DATABASE_PATH}"
        )

    async def _create_tables(self) -> None:
        """Create all database tables from ORM models."""
        from app.database.base import Base

        # Import all models so they register with Base.metadata
        import app.models.provider  # noqa: F401
        import app.models.model  # noqa: F401
        import app.models.chat  # noqa: F401
        import app.models.message_step  # noqa: F401
        import app.models.agent  # noqa: F401

        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        logger.info("SQLite tables created/verified")

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
            logger.info("SQLite database engine disposed")