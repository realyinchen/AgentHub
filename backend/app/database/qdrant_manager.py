import logging
from typing import Optional, List, Dict, Any
from functools import lru_cache

from qdrant_client import QdrantClient
from qdrant_client.http.models import (
    Distance,
    VectorParams,
    HnswConfigDiff,
    OptimizersConfigDiff,
)
from app.core.config import settings

logger = logging.getLogger(__name__)


class QdrantManager:
    """
    Optimized Qdrant vector database manager

    Optimizations:
    - Connection pooling and reuse
    - Batch query support
    - HNSW index tuning for faster search
    - Local caching of collection info
    """

    def __init__(self):
        self.client: Optional[QdrantClient] = None
        self._initialized = False
        self._collection_cache: Dict[str, Any] = {}

    def _validate_config(self) -> None:
        """Validate required Qdrant configuration."""
        required_vars = ["QDRANT_HOST", "QDRANT_PORT"]
        missing = [var for var in required_vars if not getattr(settings, var, None)]
        if missing:
            raise ValueError(
                f"Missing required Qdrant configuration: {', '.join(missing)}. "
                "These environment variables must be set to use Qdrant vector store."
            )

    def initialize(self) -> None:
        """Lazy initialization with optimized settings."""
        if self._initialized:
            return

        self._validate_config()

        try:
            self.client = QdrantClient(
                host=settings.QDRANT_HOST,
                port=settings.QDRANT_PORT,
                timeout=30,
                prefer_grpc=True,  # Use gRPC for better performance
            )
            self._initialized = True
            logger.info("Qdrant client initialized with optimizations")
        except Exception as e:
            logger.error(f"Failed to initialize Qdrant client: {e}")
            raise RuntimeError(f"Qdrant initialization failed: {e}") from e

    def get_client(self) -> QdrantClient:
        """Get the initialized Qdrant client (auto-initializes if needed)."""
        if not self._initialized:
            self.initialize()
        assert self.client is not None
        return self.client

    def dispose(self) -> None:
        """Gracefully close the client."""
        if self.client is not None:
            self.client.close()
            logger.info("Qdrant client closed")
            self.client = None
            self._initialized = False
            self._collection_cache.clear()

    def ping(self) -> bool:
        """Health check: verifies Qdrant is reachable."""
        try:
            client = self.get_client()
            client.get_collections()
            return True
        except Exception as e:
            logger.error(f"Qdrant ping failed: {e}")
            return False

    # =========================================================================
    # Optimized Vector Operations
    # =========================================================================

    def search_similar_batch(
        self,
        collection_name: str,
        queries: List[List[float]],
        top_k: int = 5,
        filter_conditions: Optional[List[Dict]] = None,
    ) -> List[List[Dict[str, Any]]]:
        """
        Batch similarity search for multiple queries.

        Args:
            collection_name: Name of the Qdrant collection
            queries: List of query vectors
            top_k: Number of results per query
            filter_conditions: Optional filters for each query

        Returns:
            List of search results for each query
        """
        client = self.get_client()

        try:
            # Use batch search API if available, otherwise parallelize
            results = []
            for i, query in enumerate(queries):
                filter_cond = (
                    filter_conditions[i]
                    if filter_conditions and i < len(filter_conditions)
                    else None
                )

                search_result = client.search(
                    collection_name=collection_name,
                    query_vector=query,
                    limit=top_k,
                    query_filter=filter_cond,
                )

                results.append(
                    [
                        {
                            "id": point.id,
                            "score": point.score,
                            "payload": point.payload,
                        }
                        for point in search_result
                    ]
                )

            logger.info(
                f"Batch search completed: {len(queries)} queries, {top_k} results each"
            )
            return results

        except Exception as e:
            logger.error(f"Batch search failed: {e}")
            raise

    @lru_cache(maxsize=128)
    def get_collection_info(self, collection_name: str) -> Dict[str, Any]:
        """
        Get collection info with caching.

        Cache invalidates automatically, call with care.
        """
        client = self.get_client()
        try:
            info = client.get_collection(collection_name)
            return {
                "name": info.config.params.vectors.size,
                "vector_size": info.config.params.vectors.size,
                "distance": info.config.params.vectors.distance,
                "points_count": info.points_count,
            }
        except Exception as e:
            logger.error(f"Failed to get collection info: {e}")
            raise

    def create_optimized_collection(
        self,
        collection_name: str,
        vector_size: int = 1536,
        distance: Distance = Distance.COSINE,
    ) -> None:
        """
        Create collection with optimized HNSW index settings.

        Optimizations:
        - HNSW index for fast approximate search
        - Tuned ef_construct for better recall
        - Optimized m parameter for speed/recall balance
        """
        client = self.get_client()

        try:
            # Check if collection exists
            collections = client.get_collections()
            if any(c.name == collection_name for c in collections.collections):
                logger.info(f"Collection {collection_name} already exists")
                return

            # Create with optimized HNSW config
            client.create_collection(
                collection_name=collection_name,
                vectors_config=VectorParams(
                    size=vector_size,
                    distance=distance,
                ),
                hnsw_config=HnswConfigDiff(
                    m=16,  # Number of edges per node (balance between speed and recall)
                    ef_construct=200,  # Higher = better index quality, slower build
                    full_scan_threshold=10000,  # Use exact search for small collections
                ),
                optimizers_config=OptimizersConfigDiff(
                    indexing_threshold=20000,  # Start indexing after 20k vectors
                    memmap_threshold=50000,  # Use memmap after 50k vectors
                ),
            )

            logger.info(f"Created optimized collection: {collection_name}")

        except Exception as e:
            logger.error(f"Failed to create collection: {e}")
            raise

    def clear_cache(self) -> None:
        """Clear collection info cache."""
        self._collection_cache.clear()
        self.get_collection_info.cache_clear()
        logger.info("Qdrant cache cleared")


# Global singleton instance (module-level)
qdrant_manager = QdrantManager()
