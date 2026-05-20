"""
PostgreSQL vector store backend (PGVector extension).

Provides semantic search capability using the pgvector PostgreSQL extension.
Replaces Qdrant with native PostgreSQL vector storage for simplified
infrastructure (single database for relational + vector data).
"""

from __future__ import annotations

import logging
from typing import (
    Any,
    Awaitable,
    Callable,
    Optional,
)

from langchain_postgres import PGVector
from langchain_core.documents import Document

from app.infra.config import get_settings

logger = logging.getLogger(__name__)

_DEFAULT_COLLECTION = "documents"


class PGVectorVectorstore:
    """
    PGVector vector store backend using LangChain's langchain-postgres.

    Provides semantic search using the PostgreSQL pgvector extension.
    All vector data is stored in the same PostgreSQL instance as relational data.
    """

    def __init__(self) -> None:
        self._store: Optional[PGVector] = None
        self._embed_fn: Optional[Callable[[str], Awaitable[list[float]]]] = None
        self._initialized = False

    def set_embed_fn(self, fn: Callable[[str], Awaitable[list[float]]]) -> None:
        """Inject text→embedding function (called by factory)."""
        self._embed_fn = fn

    @property
    def store(self) -> PGVector:
        if self._store is None:
            raise RuntimeError("Vectorstore not initialized. Call initialize() first.")
        return self._store

    async def initialize(self) -> None:
        """Initialize the PGVector store."""
        if self._initialized:
            logger.warning("PGVector store already initialized, skipping")
            return

        settings = get_settings()
        self._store = PGVector(
            connection=settings.get_postgres_libpq_url(),
            collection_name=_DEFAULT_COLLECTION,
            embeddings=None,  # We'll handle embeddings manually
            # Embedding dimension is auto-detected when adding documents
        )
        self._initialized = True
        logger.info("PGVector store initialized (PostgreSQL pgvector extension)")

    async def search(
        self, collection_name: str, query_text: str, limit: int = 5
    ) -> list[dict[str, Any]]:
        """Search by text (uses injected embed_fn)."""
        if self._embed_fn is None:
            raise ValueError(
                "No embedding function configured. The vectorstore search requires "
                "an embedding model. Please configure at least one Embedding model."
            )
        if self._store is None:
            raise RuntimeError("Vectorstore not initialized")

        embedding = await self._embed_fn(query_text)
        return await self.search_with_embedding(
            collection_name=collection_name, embedding=embedding, limit=limit
        )

    async def search_with_embedding(
        self,
        collection_name: str,
        embedding: list[float],
        limit: int = 5,
    ) -> list[dict[str, Any]]:
        """Search by pre-computed embedding vector."""
        if self._store is None:
            raise RuntimeError("Vectorstore not initialized")

        # Note: PGVector.similarity_search_with_score_by_vector works at
        # collection level; we use metadata to distinguish namespaces
        results = self._store.similarity_search_with_score_by_vector(
            embedding=embedding,
            k=limit,
        )

        return [
            {
                "id": str(doc.metadata.get("id", "")),
                "score": float(score),
                "payload": {
                    "content": doc.page_content,
                    **{
                        k: v
                        for k, v in doc.metadata.items()
                        if k not in ("id", "vector_id")
                    },
                },
            }
            for doc, score in results
        ]

    async def add_documents(
        self,
        collection_name: str,
        documents: list[dict[str, Any]],
        embeddings: list[list[float]],
    ) -> list[str]:
        """Add documents with their pre-computed embeddings."""
        if self._store is None:
            raise RuntimeError("Vectorstore not initialized")

        # Convert to LangChain Document format
        docs = [
            Document(
                page_content=doc.get("content", ""),
                metadata={
                    k: v for k, v in doc.items() if k not in ("content", "embedding")
                },
            )
            for doc in documents
        ]

        # Use PGVector's add_embeddings method
        ids = self._store.add_embeddings(
            text_embeddings=zip(
                [doc.page_content for doc in docs],
                embeddings,
            ),
            metadatas=[doc.metadata for doc in docs],
        )

        logger.info(
            "Added %d documents to PGVector collection '%s'",
            len(ids),
            collection_name,
        )
        return [str(id) for id in ids]

    async def dispose(self) -> None:
        """Clean up resources (PGVector manages its own connections)."""
        if self._store is not None:
            self._store = None
            self._initialized = False
            logger.info("PGVector store disposed")
