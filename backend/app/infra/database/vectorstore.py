"""PostgreSQL vector store backend (PGVector extension).

Provides semantic search capability using the pgvector PostgreSQL extension.
Uses LangChain's official PGEngine + PGVectorStore API for production-ready
vector storage.

Embedding functions are provided by infra.llm.embedding module (singleton
LiteLLMEmbeddings instance created at startup).

Reference:
https://docs.langchain.com/oss/python/integrations/vectorstores/index#pgvectorstore
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings
from langchain_postgres import PGEngine, PGVectorStore

from app.infra.config import get_settings
from app.infra.errors import VectorStoreError

logger = logging.getLogger(__name__)

_DEFAULT_TABLE = "langchain_pg_embedding"


# ── TTL Helper Functions ─────────────────────────────────────────────────────


def build_ttl_filter(
    expires_at_field: str = "expires_at",
) -> dict[str, Any]:
    """Build a metadata filter to exclude expired documents.

    Use this filter with search() to automatically exclude documents
    that have an expires_at timestamp in the past.

    Args:
        expires_at_field: Metadata field name for expiration timestamp.
                         Defaults to 'expires_at'.

    Returns:
        Filter dict for use with search() method.

    Example:
        filter = build_ttl_filter()
        results = await vectorstore.search("collection", "query", filter=filter)
    """
    now = datetime.now(timezone.utc).isoformat()
    return {
        "$or": [
            {expires_at_field: {"$exists": False}},  # No expiration
            {expires_at_field: {"$gt": now}},  # Not yet expired
        ]
    }


def build_expires_at_metadata(
    ttl_days: Optional[int] = None,
    ttl_hours: Optional[int] = None,
    expires_at: Optional[datetime] = None,
) -> dict[str, Any]:
    """Build metadata dict with expiration timestamp for TTL support.

    Add this to document metadata when adding documents to enable
    automatic expiration filtering during search.

    Args:
        ttl_days: Number of days until expiration.
        ttl_hours: Number of hours until expiration.
        expires_at: Explicit expiration datetime.

    Only one of ttl_days, ttl_hours, or expires_at should be provided.
    If none provided, returns empty dict (no expiration).

    Returns:
        Metadata dict with expires_at field.

    Example:
        # Document expires in 30 days
        metadata = build_expires_at_metadata(ttl_days=30)
        await vectorstore.add_documents(
            "collection",
            [{"content": "...", **metadata}],
            embeddings=[...],
        )
    """
    if expires_at is not None:
        return {"expires_at": expires_at.isoformat()}
    elif ttl_days is not None:
        exp = datetime.now(timezone.utc) + timedelta(days=ttl_days)
        return {"expires_at": exp.isoformat()}
    elif ttl_hours is not None:
        exp = datetime.now(timezone.utc) + timedelta(hours=ttl_hours)
        return {"expires_at": exp.isoformat()}
    return {}


class PGVectorVectorstore:
    """
    PGVector vector store backend using LangChain's PGVectorStore.

    Provides semantic search using the PostgreSQL pgvector extension.
    Uses the official PGEngine + PGVectorStore API for production readiness.

    Embedding functions are injected from infra.llm.embedding module.

    Multi-table support:
        Each instance is bound to a specific table (collection).
        Use get_vectorstore(table_name) to get/create instance for a collection.
    """

    def __init__(self, table_name: str = _DEFAULT_TABLE) -> None:
        """Initialize vectorstore for a specific table/collection.

        Args:
            table_name: PostgreSQL table name for storing vectors.
                       Defaults to 'langchain_pg_embedding'.
        """
        self._table_name = table_name
        self._store: Optional[PGVectorStore] = None
        self._engine: Optional[PGEngine] = None
        self._embeddings: Optional[Embeddings] = None
        self._initialized = False

    def set_embed_fn(
        self,
        embed_fn=None,
        embed_batch_fn=None,
        embeddings: Optional[Embeddings] = None,
    ) -> None:
        """Inject embeddings instance or functions (called by factory).

        Args:
            embed_fn: Optional async embed function (for backward compatibility).
            embed_batch_fn: Optional async batch embed function.
            embeddings: LangChain Embeddings instance (preferred).

        The embeddings instance is preferred as it follows LangChain's standard
        interface and can be passed directly to PGVectorStore.
        """
        if embeddings is not None:
            self._embeddings = embeddings
        elif embed_fn is not None:
            # Wrap function in adapter for backward compatibility
            from app.infra.llm.embedding import LiteLLMEmbeddings

            if isinstance(embed_fn, LiteLLMEmbeddings):
                self._embeddings = embed_fn
            else:
                # Create adapter for raw functions (deprecated path)
                self._embeddings = _FunctionEmbeddingsAdapter(
                    embed_fn=embed_fn, embed_batch_fn=embed_batch_fn
                )

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

        if self._embeddings is None:
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

        # Create PGVectorStore (async factory method)
        try:
            self._store = await PGVectorStore.create(
                engine=self._engine,
                table_name=self._table_name,
                embedding_service=self._embeddings,
            )
            logger.info("PGVectorStore initialized with table '%s'", self._table_name)
        except Exception as e:
            raise VectorStoreError(
                f"Failed to create PGVectorStore: {e}",
                operation="initialize",
            ) from e

        self._initialized = True

    async def search(
        self,
        collection_name: str,
        query_text: str,
        limit: int = 5,
        filter: Optional[dict] = None,
    ) -> list[dict[str, Any]]:
        """Search by text (uses internal embedding_service).

        Args:
            collection_name: Collection/table name (for multi-table support).
            query_text: Text to search for similar documents.
            limit: Maximum number of results to return.
            filter: Optional metadata filter (e.g., {"expires_at": {"$gt": "2026-01-01"}}).
                   Use TTLFilter helper for common TTL patterns.
        """
        if self._store is None:
            raise VectorStoreError(
                "Vectorstore not initialized",
                collection_name=collection_name,
                operation="search",
            )

        try:
            # Build filter kwargs for PGVectorStore
            search_kwargs = {"query": query_text, "k": limit}
            if filter:
                search_kwargs["filter"] = filter

            results = await self._store.asimilarity_search_with_score(**search_kwargs)
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


class _FunctionEmbeddingsAdapter(Embeddings):
    """Adapter to wrap raw embed functions into LangChain Embeddings interface.

    Used for backward compatibility when raw functions are passed instead of
    an Embeddings instance.
    """

    def __init__(
        self,
        embed_fn,
        embed_batch_fn=None,
    ):
        self._embed_fn = embed_fn
        self._embed_batch_fn = embed_batch_fn

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """Sync embed - not supported in async context."""
        raise NotImplementedError(
            "Synchronous embedding not supported. Use aembed_documents() instead."
        )

    def embed_query(self, text: str) -> list[float]:
        """Sync embed - not supported in async context."""
        raise NotImplementedError(
            "Synchronous embedding not supported. Use aembed_query() instead."
        )

    async def aembed_documents(self, texts: list[str]) -> list[list[float]]:
        """Embed a list of texts asynchronously."""
        if self._embed_batch_fn:
            return await self._embed_batch_fn(texts)
        # Fallback: embed one by one
        results = []
        for text in texts:
            embedding = await self._embed_fn(text)
            results.append(embedding)
        return results

    async def aembed_query(self, text: str) -> list[float]:
        """Embed a single query text asynchronously."""
        return await self._embed_fn(text)
