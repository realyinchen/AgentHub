"""
Database Abstraction Interfaces

Defines the abstract interfaces that all database/vectorstore/checkpointer
backends must implement. Business code depends on these interfaces, never
on concrete backend implementations.
"""

from abc import ABC, abstractmethod
from contextlib import asynccontextmanager
from typing import AsyncGenerator, Any, Optional


class DatabaseInterface(ABC):
    """
    Abstract interface for relational database backends.

    Implementations: PostgresDatabase, SQLiteDatabase
    """

    @abstractmethod
    async def initialize(self) -> None:
        """Initialize the database engine and connection pool."""
        ...

    @abstractmethod
    @asynccontextmanager
    async def session(self) -> AsyncGenerator[Any, None]:
        """
        Yield a database session with auto-commit semantics.

        Commits on success, rolls back on exception.
        Callers should NOT need to call commit() explicitly,
        but doing so is harmless (double-commit is a no-op).
        """
        ...
        yield  # pragma: no cover

    @abstractmethod
    async def execute_query(self, query: Any, params: Optional[dict] = None) -> Any:
        """Execute a raw SQL query and return results."""
        ...

    @abstractmethod
    async def dispose(self) -> None:
        """Dispose of the database engine and all connections."""
        ...


class VectorstoreInterface(ABC):
    """
    Abstract interface for vector store backends.

    Implementations: QdrantVectorstore, SqliteVecVectorstore
    """

    @abstractmethod
    async def initialize(self) -> None:
        """Initialize the vector store client and ensure collection exists."""
        ...

    @abstractmethod
    async def dispose(self) -> None:
        """Dispose of the vector store client and release resources."""
        ...

    @abstractmethod
    async def search(
        self, collection_name: str, query_text: str, limit: int = 5
    ) -> list[dict]:
        """Search the vector store by text query (auto-embed)."""
        ...

    @abstractmethod
    async def search_with_embedding(
        self,
        collection_name: str,
        embedding: list[float],
        limit: int = 5,
    ) -> list[dict]:
        """Search the vector store by pre-computed embedding vector."""
        ...


class CheckpointInterface(ABC):
    """
    Abstract interface for LangGraph checkpoint backends.

    Implementations: PostgresCheckpointer, SqliteCheckpointer
    """

    @abstractmethod
    async def initialize(self) -> None:
        """Initialize the checkpointer and create tables if needed."""
        ...

    @abstractmethod
    async def dispose(self) -> None:
        """Dispose of the checkpointer and release resources."""
        ...

    @abstractmethod
    def get_saver(self):
        """Return the LangGraph-compatible saver instance."""
        ...
