import logging
from contextlib import asynccontextmanager, contextmanager
from typing import Optional
from sqlalchemy import text, create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import QueuePool
from sqlalchemy.ext.asyncio import (
    create_async_engine,
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
)
from sqlalchemy.pool import AsyncAdaptedQueuePool

from app.core.config import settings

logger = logging.getLogger(__name__)


class AsyncDatabaseManager:
    """
    Asynchronous PostgreSQL database manager
    - Uses asyncpg + SQLAlchemy async extensions
    - Designed for Agent tools, FastAPI async routes, and LangGraph async nodes
    - Supports delayed initialization and graceful shutdown
    """

    def __init__(self):
        self.engine: Optional[AsyncEngine] = None
        self.session_factory: Optional[async_sessionmaker] = None
        self._initialized = False

    async def initialize(self):
        """Lazy initialization – call during startup or first use"""
        if self._initialized:
            return

        self.engine = create_async_engine(
            settings.ASYNC_POSTGRE_URL,
            poolclass=AsyncAdaptedQueuePool,  # Explicitly use async-compatible pool
            pool_pre_ping=True,
            pool_size=5,
            max_overflow=15,
            pool_timeout=30,
            pool_recycle=1800,
            connect_args={
                "server_settings": {
                    "application_name": f"{settings.POSTGRES_APPLICATION_NAME}"
                },
            },
            # echo=True,  # Uncomment during development to log all SQL
        )

        self.session_factory = async_sessionmaker(
            self.engine,
            class_=AsyncSession,
            expire_on_commit=False,
            autoflush=False,
            autocommit=False,  # Explicitly disable autocommit
        )

        self._initialized = True
        logger.info("Async PostgreSQL engine initialized with asyncpg")

    @asynccontextmanager
    async def session(self):
        """Async session context manager - automatically commits/rolls back and closes"""
        if not self._initialized:
            await self.initialize()

        session = self.session_factory()  # type: ignore
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()

    async def dispose(self):
        """Gracefully dispose of the engine (called during shutdown)"""
        if self.engine:
            await self.engine.dispose()
            logger.info("Async database engine disposed")
            self.engine = None
            self.session_factory = None
            self._initialized = False

    async def ping(self) -> bool:
        """Health check: verifies the database connection is alive"""
        try:
            async with self.session() as session:
                await session.execute(text("SELECT 1"))
            return True
        except Exception as e:
            logger.error(f"Database ping failed: {e}")
            return False


class DatabaseManager:
    """
    Synchronous PostgreSQL database manager
    - Uses psycopg + SQLAlchemy synchronous extensions
    - Designed for CLI scripts, background tasks, tests, or non-async contexts
    - Supports delayed initialization and graceful shutdown
    """

    def __init__(self):
        self.engine: Optional[Engine] = None
        self.session_factory: Optional[sessionmaker] = None
        self._initialized = False

    def initialize(self):
        """Lazy initialization – call during startup or first use"""
        if self._initialized:
            return

        self.engine = create_engine(
            settings.POSTGRE_URL,
            poolclass=QueuePool,
            pool_pre_ping=True,
            pool_size=5,
            max_overflow=15,
            pool_timeout=30,
            pool_recycle=1800,
            connect_args={
                "server_settings": {
                    "application_name": f"{settings.POSTGRES_APPLICATION_NAME}"
                },
            },
            # echo=True,  # Uncomment during development to log all SQL
        )

        self.session_factory = sessionmaker(
            bind=self.engine,
            autoflush=False,
            autocommit=False,  # Explicitly disable autocommit
            expire_on_commit=False,
        )

        self._initialized = True
        logger.info("Synchronous PostgreSQL engine initialized")

    @contextmanager
    def session(self):
        """Synchronous session context manager - automatically commits/rolls back and closes"""
        if not self._initialized:
            self.initialize()

        session = self.session_factory()  # type: ignore
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def dispose(self):
        """Gracefully dispose of the engine (called during shutdown)"""
        if self.engine:
            self.engine.dispose()
            logger.info("Synchronous database engine disposed")
            self.engine = None
            self.session_factory = None
            self._initialized = False

    def ping(self) -> bool:
        """Health check: verifies the database connection is alive"""
        try:
            with self.session() as session:
                session.execute(text("SELECT 1"))
            return True
        except Exception as e:
            logger.error(f"Database ping failed: {e}")
            return False


# Global singleton instance (module-level)
adb_manager = AsyncDatabaseManager()
db_manager = DatabaseManager()
