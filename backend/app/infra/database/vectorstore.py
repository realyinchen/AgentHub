"""
PostgreSQL vector store backend (PGVector extension).

Provides semantic search capability using the pgvector PostgreSQL extension.
Uses LangChain's official PGEngine + PGVectorStore API for production-ready
vector storage.

Reference:
https://docs.langchain.com/oss/python/integrations/vectorstores/index#pgvectorstore
"""

from __future__ import annotations

import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Awaitable, Callable, Optional, Sequence

from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings
from langchain_postgres import PGEngine, PGVectorStore

from app.infra.config import get_settings
from app.infra.errors import VectorStoreError

logger = logging.getLogger(__name__)

_DEFAULT_TABLE = "langchain_pg_embedding"


class LiteLLMEmbeddingsAdapter(Embeddings):
    """
    Adapter to use LiteLLM embedding with LangChain's PGVectorStore.

    Wraps the async embedding function from ModelManager into LangChain's
    Embeddings interface (which expects sync methods).

    Note: PGVectorStore calls embed_documents/embed_query synchronously,
    so we need to run the async embedding in an event loop.
    """

    def __init__(
        self,
        embed_fn: Callable[[str], Awaitable[list[float]]],
        embed_batch_fn: Optional[
            Callable[[Sequence[str]], Awaitable[list[list[float]]]]
        ] = None,
    ):
        """Initialize the adapter.

        Args:
            embed_fn: Async function to embed a single text.
            embed_batch_fn: Optional async function to embed multiple texts.
                           If not provided, texts are embedded one by one.
        """
        self._embed_fn = embed_fn
        self._embed_batch_fn = embed_batch_fn

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """Embed a list of texts (synchronous wrapper)."""
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop is not None:
            # We're inside an async context, run in thread pool
            with ThreadPoolExecutor() as pool:
                future = pool.submit(asyncio.run, self._embed_documents_async(texts))
                return future.result()
        else:
            return asyncio.run(self._embed_documents_async(texts))

    async def _embed_documents_async(self, texts: list[str]) -> list[list[float]]:
        """Embed a list of texts asynchronously."""
        if self._embed_batch_fn:
            return await self._embed_batch_fn(texts)
        # Fallback: embed one by one
        results = []
        for text in texts:
            embedding = await self._embed_fn(text)
            results.append(embedding)
        return results

    def embed_query(self, text: str) -> list[float]:
        """Embed a single query text (synchronous wrapper)."""
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        async def _get_embedding() -> list[float]:
            return await self._embed_fn(text)

        if loop is not None:
            with ThreadPoolExecutor() as pool:
                future = pool.submit(asyncio.run, _get_embedding())
                return future.result()
        else:
            return asyncio.run(_get_embedding())

    async def aembed_documents(self, texts: list[str]) -> list[list[float]]:
        """Embed a list of texts asynchronously."""
        return await self._embed_documents_async(texts)

    async def aembed_query(self, text: str) -> list[float]:
        """Embed a single query text asynchronously."""
        return await self._embed_fn(text)


class PGVectorVectorstore:
    """
    PGVector vector store backend using LangChain's PGVectorStore.

    Provides semantic search using the PostgreSQL pgvector extension.
    Uses the official PGEngine + PGVectorStore API for production readiness.
    """

    def __init__(self) -> None:
        self._store: Optional[PGVectorStore] = None
        self._engine: Optional[PGEngine] = None
        self._embed_fn: Optional[Callable[[str], Awaitable[list[float]]]] = None
        self._embed_batch_fn: Optional[
            Callable[[Sequence[str]], Awaitable[list[list[float]]]]
        ] = None
        self._initialized = False

    def set_embed_fn(
        self,
        fn: Callable[[str], Awaitable[list[float]]],
        batch_fn: Optional[
            Callable[[Sequence[str]], Awaitable[list[list[float]]]]
        ] = None,
    ) -> None:
        """Inject text→embedding function (called by factory)."""
        self._embed_fn = fn
        self._embed_batch_fn = batch_fn

    @property
    def store(self) -> PGVectorStore:
        if self._store is None:
            raise RuntimeError("Vectorstore not initialized. Call initialize() first.")
        return self._store

    async def initialize(self) -> None:
        """Initialize the PGVector store."""
        if self._initialized:
            logger.warning("PGVector store already initialized, skipping")
            return

        if self._embed_fn is None:
            raise VectorStoreError(
                "No embedding function configured. "
                "Call set_embed_fn() before initialize().",
                operation="initialize",
            )

        settings = get_settings()
        conn_url = settings.get_postgres_libpq_url()

        try:
            self._engine = PGEngine.from_connection_string(url=conn_url)
            logger.info("PGEngine created for PGVectorStore")
        except Exception as e:
            raise VectorStoreError(
                f"Failed to create PGEngine: {e}",
                operation="initialize",
            ) from e

        # Create embeddings adapter
        embeddings = LiteLLMEmbeddingsAdapter(
            embed_fn=self._embed_fn,
            embed_batch_fn=self._embed_batch_fn,
        )

        # Create PGVectorStore (async factory method)
        try:
            self._store = await PGVectorStore.create(
                engine=self._engine,
                table_name=_DEFAULT_TABLE,
                embedding_service=embeddings,
            )
            logger.info("PGVectorStore initialized with table '%s'", _DEFAULT_TABLE)
        except Exception as e:
            raise VectorStoreError(
                f"Failed to create PGVectorStore: {e}",
                operation="initialize",
            ) from e

        self._initialized = True

    async def search(
        self, collection_name: str, query_text: str, limit: int = 5
    ) -> list[dict[str, Any]]:
        """Search by text (uses internal embedding_service)."""
        if self._store is None:
            raise VectorStoreError(
                "Vectorstore not initialized",
                collection_name=collection_name,
                operation="search",
            )

        try:
            results = await self._store.asimilarity_search_with_score(
                query=query_text,
                k=limit,
            )
            return self._format_results(results)
        except Exception as e:
            raise VectorStoreError(
                f"Vector search failed: {e}",
                collection_name=collection_name,
                operation="search",
            ) from e

    async def search_with_embedding(
        self,
        collection_name: str,
        embedding: list[float],
        limit: int = 5,
    ) -> list[dict[str, Any]]:
        """Search by pre-computed embedding vector."""
        if self._store is None:
            raise VectorStoreError(
                "Vectorstore not initialized",
                collection_name=collection_name,
                operation="search_with_embedding",
            )

        try:
            results = await self._store.asimilarity_search_with_score_by_vector(
                embedding=embedding,
                k=limit,
            )
            return self._format_results(results)
        except Exception as e:
            raise VectorStoreError(
                f"Vector search by embedding failed: {e}",
                collection_name=collection_name,
                operation="search_with_embedding",
            ) from e

    async def add_documents(
        self,
        collection_name: str,
        documents: list[dict[str, Any]],
        embeddings: list[list[float]],
    ) -> list[str]:
        """Add documents with their pre-computed embeddings."""
        if self._store is None:
            raise VectorStoreError(
                "Vectorstore not initialized",
                collection_name=collection_name,
                operation="add_documents",
            )

        try:
            # Convert to LangChain Document format
            docs = [
                Document(
                    page_content=doc.get("content", ""),
                    metadata={
                        k: v
                        for k, v in doc.items()
                        if k not in ("content", "embedding")
                    },
                )
                for doc in documents
            ]

            # Use add_embeddings for pre-computed embeddings
            ids = await self._store.aadd_embeddings(
                texts=[doc.page_content for doc in docs],
                embeddings=embeddings,
                metadatas=[doc.metadata for doc in docs],
            )

            logger.info("Added %d documents to PGVectorStore", len(ids))
            return [str(id) for id in ids]
        except Exception as e:
            raise VectorStoreError(
                f"Failed to add documents: {e}",
                collection_name=collection_name,
                operation="add_documents",
            ) from e

    def _format_results(
        self, results: list[tuple[Document, float]]
    ) -> list[dict[str, Any]]:
        """Format LangChain search results to dict format."""
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

    async def dispose(self) -> None:
        """Clean up resources."""
        if self._store is not None:
            self._store = None
            self._engine = None
            self._initialized = False
            logger.info("PGVectorStore disposed")
