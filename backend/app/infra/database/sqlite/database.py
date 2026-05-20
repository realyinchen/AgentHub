"""
SQLite database backend (development / testing).

Provides SQLAlchemy async engine + aiosqlite for relational data persistence.
For development/test stacks only; production uses postgres.
"""

from __future__ import annotations

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

from app.infra.config import get_settings

logger = logging.getLogger(__name__)


class SQLiteDatabase:
    """SQLite database backend using SQLAlchemy async engine + aiosqlite.

    Public interface is identical to PostgresDatabase — both expose
    ``session()`` as an async context manager so business code (CRUD,
    FastAPI Depends) is fully backend-agnostic.
    """

    def __init__(self) -> None:
        self._engine: AsyncEngine | None = None
        self._session_factory: async_sessionmaker[AsyncSession] | None = None

    async def initialize(self) -> None:
        if self._engine is not None:
            logger.warning("SQLite database already initialized, skipping")
            return

        settings = get_settings()
        db_path = settings.SQLITE_DATABASE_PATH
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)

        db_url = f"sqlite+aiosqlite:///{db_path}"
        self._engine = create_async_engine(
            db_url,
            echo=False,
            future=True,
            connect_args={"check_same_thread": False},
            pool_pre_ping=True,
        )
        self._session_factory = async_sessionmaker(
            self._engine,
            class_=AsyncSession,
            expire_on_commit=False,
        )
        logger.info("SQLite database initialized (db: %s)", db_path)

    @property
    def engine(self) -> AsyncEngine:
        if self._engine is None:
            raise RuntimeError("Database not initialized. Call initialize() first.")
        return self._engine

    async def get_session(self) -> AsyncGenerator[AsyncSession, None]:
        """FastAPI Depends compatible: yields async session.

        Kept for compatibility with code that prefers the Depends pattern.
        Prefer ``session()`` (async context manager) for new code — it has
        the exact same signature as PostgresDatabase.session().
        """
        if self._session_factory is None:
            raise RuntimeError("Database not initialized. Call initialize() first.")
        async with self._session_factory() as session:
            yield session

    @asynccontextmanager
    async def session(self) -> AsyncGenerator[AsyncSession, None]:
        """Yield an async session with auto-commit/rollback semantics.

        Signature and semantics are identical to ``PostgresDatabase.session()``,
        making business code completely backend-agnostic.
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

    async def dispose(self) -> None:
        if self._engine is not None:
            await self._engine.dispose()
            self._engine = None
            self._session_factory = None
            logger.info("SQLite database disposed")
