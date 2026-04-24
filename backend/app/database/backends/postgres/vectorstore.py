"""
Qdrant Vectorstore Backend

Implements VectorstoreInterface using AsyncQdrantClient for non-blocking I/O.
Collection is created lazily on first use if it doesn't exist.
"""

import logging
from typing import Optional

from qdrant_client import AsyncQdrantClient

from app.core.config import settings
from app.database.interfaces import VectorstoreInterface

logger = logging.getLogger(__name__)

# Default vector size for common embedding models
_DEFAULT_VECTOR_SIZE = 1024


class QdrantVectorstore(VectorstoreInterface):
    """Qdrant vector store backend using async client."""

    def __init__(self) -> None:
        self._client: Optional[AsyncQdrantClient] = None

    @property
    def client(self) -> AsyncQdrantClient:
        """Get the async Qdrant client, raising if not initialized."""
        if self._client is None:
            raise RuntimeError("Vectorstore not initialized. Call initialize() first.")
        return self._client

    async def initialize(self) -> None:
        """Initialize the async Qdrant client."""
        if self._client is not None:
            logger.warning("Qdrant vectorstore already initialized, skipping")
            return

        self._client = AsyncQdrantClient(
            host=settings.QDRANT_HOST,
            port=settings.QDRANT_PORT,
        )
        logger.info(
            f"Qdrant async client initialized ({settings.QDRANT_HOST}:{settings.QDRANT_PORT})"
        )

    async def _ensure_collection(
        self, collection_name: str, vector_size: int = _DEFAULT_VECTOR_SIZE
    ) -> None:
        """Create collection if it doesn't exist."""
        collections = await self.client.get_collections()
        existing = [c.name for c in collections.collections]
        if collection_name not in existing:
            from qdrant_client.models import Distance, VectorParams

            await self.client.create_collection(
                collection_name=collection_name,
                vectors_config=VectorParams(size=vector_size, distance=Distance.COSINE),
            )
            logger.info(f"Created Qdrant collection: {collection_name}")

    async def search(
        self, collection_name: str, query_text: str, limit: int = 5
    ) -> list[dict]:
        """
        Search the vector store by text query.

        Note: This requires an embedding model to convert text to vectors.
        Currently delegates to the QdrantVectorStore from langchain-qdrant
        in the vectorstore_retriever tool for text-to-embedding conversion.
        """
        raise NotImplementedError(
            "Text search requires embedding. Use search_with_embedding() instead, "
            "or use the vectorstore_retriever tool which handles embedding."
        )

    async def search_with_embedding(
        self,
        collection_name: str,
        embedding: list[float],
        limit: int = 5,
    ) -> list[dict]:
        """Search the vector store by pre-computed embedding vector."""
        await self._ensure_collection(collection_name, vector_size=len(embedding))

        results = await self.client.search(
            collection_name=collection_name,
            query_vector=embedding,
            limit=limit,
        )

        return [
            {
                "id": str(result.id),
                "score": result.score,
                "payload": result.payload or {},
            }
            for result in results
        ]

    async def dispose(self) -> None:
        """Close the async Qdrant client."""
        if self._client is not None:
            await self._client.close()
            self._client = None
            logger.info("Qdrant async client disposed")
