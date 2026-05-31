"""
Database component protocols.

Defines interfaces for database components, enabling:
- Clear contracts between layers
- Easy mocking in tests
- Future backend implementations (if needed)

All protocols follow LangChain/LangGraph integration patterns.
"""

from __future__ import annotations

from typing import (
    Any,
    AsyncContextManager,
    Awaitable,
    Callable,
    Optional,
    Protocol,
    runtime_checkable,
)

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.store.base import BaseStore
from sqlalchemy.ext.asyncio import AsyncSession


@runtime_checkable
class DatabaseInterface(Protocol):
    """Protocol for relational database backends.

    Provides SQLAlchemy async engine and session management.
    """

    @property
    def engine(self) -> Any:
        """Return the SQLAlchemy AsyncEngine."""
        ...

    def session(self) -> AsyncContextManager[AsyncSession]:
        """Yield an async session with auto-commit/rollback."""
        ...

    async def execute_query(self, query: Any, params: Optional[dict] = None) -> Any:
        """Execute a raw SQL query."""
        ...

    async def initialize(self) -> None:
        """Initialize the database connection pool."""
        ...

    async def dispose(self) -> None:
        """Dispose the database engine and connection pool."""
        ...


@runtime_checkable
class VectorstoreInterface(Protocol):
    """Protocol for vector store backends.

    Provides semantic search and document indexing using pgvector.
    Follows LangChain's vectorstore patterns.
    """

    def set_embed_fn(self, fn: Callable[[str], Awaitable[list[float]]]) -> None:
        """Inject text→embedding function."""
        ...

    async def initialize(self) -> None:
        """Initialize the vector store connection."""
        ...

    async def search(
        self,
        collection_name: str,
        query_text: str,
        limit: int = 5,
    ) -> list[dict[str, Any]]:
        """Search by text (uses injected embed_fn)."""
        ...

    async def search_with_embedding(
        self,
        collection_name: str,
        embedding: list[float],
        limit: int = 5,
    ) -> list[dict[str, Any]]:
        """Search by pre-computed embedding vector."""
        ...

    async def add_documents(
        self,
        collection_name: str,
        documents: list[dict[str, Any]],
        embeddings: list[list[float]],
    ) -> list[str]:
        """Add documents with their pre-computed embeddings."""
        ...

    async def dispose(self) -> None:
        """Clean up resources."""
        ...


@runtime_checkable
class CheckpointerInterface(Protocol):
    """Protocol for LangGraph checkpointer backends.

    Provides short-term memory (conversation state persistence).
    Returns LangGraph's AsyncPostgresSaver.
    """

    async def initialize(self) -> None:
        """Initialize the checkpointer connection."""
        ...

    def get_saver(self) -> BaseCheckpointSaver:
        """Return the LangGraph-compatible checkpoint saver."""
        ...

    async def dispose(self) -> None:
        """Dispose the checkpointer connection."""
        ...


@runtime_checkable
class StoreInterface(Protocol):
    """Protocol for LangGraph Store backends.

    Provides long-term memory (cross-session persistence).
    Returns LangGraph's AsyncPostgresStore.
    """

    async def initialize(self) -> None:
        """Initialize the store connection."""
        ...

    def get_store(self) -> BaseStore:
        """Return the LangGraph-compatible store."""
        ...

    async def aput(
        self,
        namespace: tuple[str, ...],
        key: str,
        value: dict,
        index: Optional[list[str]] = None,
    ) -> None:
        """Store a value in the given namespace."""
        ...

    async def aget(self, namespace: tuple[str, ...], key: str) -> Optional[dict]:
        """Retrieve a value by namespace and key."""
        ...

    async def asearch(
        self,
        namespace_prefix: tuple[str, ...],
        query: Optional[str] = None,
        limit: int = 10,
        filter: Optional[dict] = None,
    ) -> list[dict]:
        """Search for items in the store."""
        ...

    async def adelete(self, namespace: tuple[str, ...], key: str) -> None:
        """Delete an item from the store."""
        ...

    async def dispose(self) -> None:
        """Dispose the store connection."""
        ...


__all__ = [
    "DatabaseInterface",
    "VectorstoreInterface",
    "CheckpointerInterface",
    "StoreInterface",
]