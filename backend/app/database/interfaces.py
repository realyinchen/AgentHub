"""
Database Abstraction Interfaces

Defines the abstract interfaces that all database/vectorstore/checkpointer
backends must implement. Business code depends on these interfaces, never
on concrete backend implementations.
"""

from abc import ABC, abstractmethod
from contextlib import asynccontextmanager
from typing import AsyncGenerator, Any, Callable, Awaitable, Optional


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

    Score Semantics:
        All search methods return results with a "score" field representing
        cosine similarity (0.0 to 1.0, where 1.0 = identical).
        Backends that return cosine distance must convert: score = 1.0 - distance.
    """

    # Embedding function injected by the factory layer.
    # Vectorstore implementations should NOT import ModelManager directly.
    _embed_fn: Optional[Callable[[str], Awaitable[list[float]]]] = None

    def set_embed_fn(self, fn: Callable[[str], Awaitable[list[float]]]) -> None:
        """
        Inject an embedding function for text-to-vector conversion.

        Called by the factory after creating the instance. Business code
        should not call this directly.
        """
        self._embed_fn = fn

    @abstractmethod
    async def initialize(self) -> None:
        """Initialize the vector store client and ensure collection exists."""
        ...

    @abstractmethod
    async def dispose(self) -> None:
        """Dispose of the vector store client and release resources."""
        ...

    async def search(
        self, collection_name: str, query_text: str, limit: int = 5
    ) -> list[dict]:
        """
        Search the vector store by text query.

        Uses the injected embedding function (_embed_fn) to convert text
        to a vector, then delegates to search_with_embedding().

        Raises ValueError if no embedding function has been injected.
        """
        if self._embed_fn is None:
            raise ValueError(
                "No embedding function configured. "
                "The vectorstore search requires an embedding model. "
                "Please configure at least one Embedding model in settings."
            )
        embedding = await self._embed_fn(query_text)
        return await self.search_with_embedding(
            collection_name=collection_name, embedding=embedding, limit=limit
        )

    @abstractmethod
    async def search_with_embedding(
        self,
        collection_name: str,
        embedding: list[float],
        limit: int = 5,
    ) -> list[dict]:
        """Search the vector store by pre-computed embedding vector."""
        ...

    async def add_documents(
        self,
        collection_name: str,
        documents: list[dict],
        embeddings: list[list[float]],
    ) -> list[str]:
        """
        Add documents with pre-computed embeddings to the vector store.

        Args:
            collection_name: Name of the collection to add documents to.
            documents: List of document payloads (dicts with content/metadata).
            embeddings: Pre-computed embedding vectors, one per document.

        Returns:
            List of document IDs assigned by the store.
        """
        raise NotImplementedError(
            f"{self.__class__.__name__} does not implement add_documents()"
        )


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
