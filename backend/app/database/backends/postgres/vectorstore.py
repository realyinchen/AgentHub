"""
Qdrant Vectorstore Backend

Implements VectorstoreInterface using AsyncQdrantClient for non-blocking I/O.
Collection is created lazily on first use if it doesn't exist.
"""

import logging
from typing import Optional
from uuid import uuid4

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
        self._known_collections: set[str] = set()

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
        """Create collection if it doesn't exist.

        Uses in-memory cache to avoid redundant get_collections() calls
        on every search/add operation.
        """
        if collection_name in self._known_collections:
            return
        collections = await self.client.get_collections()
        existing = [c.name for c in collections.collections]
        if collection_name not in existing:
            from qdrant_client.models import Distance, VectorParams

            await self.client.create_collection(
                collection_name=collection_name,
                vectors_config=VectorParams(size=vector_size, distance=Distance.COSINE),
            )
            logger.info(f"Created Qdrant collection: {collection_name}")
        self._known_collections.add(collection_name)

    async def search_with_embedding(
        self,
        collection_name: str,
        embedding: list[float],
        limit: int = 5,
    ) -> list[dict]:
        """Search the vector store by pre-computed embedding vector."""
        await self._ensure_collection(collection_name, vector_size=len(embedding))

        results = await self.client.search(  # type: ignore[union-attr]
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

    async def add_documents(
        self,
        collection_name: str,
        documents: list[dict],
        embeddings: list[list[float]],
    ) -> list[str]:
        """Add documents with pre-computed embeddings to Qdrant."""
        from qdrant_client.models import PointStruct

        await self._ensure_collection(collection_name, vector_size=len(embeddings[0]))

        points = []
        ids = []
        for doc, emb in zip(documents, embeddings):
            point_id = uuid4().hex
            points.append(PointStruct(id=point_id, vector=emb, payload=doc))
            ids.append(point_id)

        await self.client.upsert(
            collection_name=collection_name,
            points=points,
        )
        logger.info(
            f"Added {len(points)} documents to Qdrant collection '{collection_name}'"
        )
        return ids

    async def dispose(self) -> None:
        """Close the async Qdrant client."""
        if self._client is not None:
            await self._client.close()
            self._client = None
            logger.info("Qdrant async client disposed")
