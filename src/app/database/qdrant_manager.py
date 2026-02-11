import logging
from typing import Optional

from qdrant_client import QdrantClient
from app.core.config import settings

logger = logging.getLogger(__name__)


class QdrantManager:
    """
    Synchronous Qdrant vector database manager
    - Wraps QdrantClient with lazy initialization and lifecycle control
    - Designed for CLI, background tasks, FastAPI sync routes, or LangGraph sync nodes
    - Supports delayed initialization, graceful shutdown, and health checks
    """

    def __init__(self):
        self.client: Optional[QdrantClient] = None
        self._initialized = False

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
        """Lazy initialization – call during startup or first use."""
        if self._initialized:
            return

        self._validate_config()

        try:
            self.client = QdrantClient(
                host=settings.QDRANT_HOST,
                port=settings.QDRANT_PORT,
                # Add other options if needed, e.g.:
                # api_key=settings.QDRANT_API_KEY,
                # https=settings.QDRANT_HTTPS,
                # timeout=30,
            )
            self._initialized = True
            logger.info("Qdrant client initialized")
        except Exception as e:
            logger.error(f"Failed to initialize Qdrant client: {e}")
            raise RuntimeError(f"Qdrant initialization failed: {e}") from e

    def get_client(self) -> QdrantClient:
        """Get the initialized Qdrant client (auto-initializes if needed)."""
        if not self._initialized:
            self.initialize()
        assert self.client is not None  # for type checker
        return self.client

    def dispose(self) -> None:
        """Gracefully close the client (call during shutdown)."""
        if self.client is not None:
            self.client.close()
            logger.info("Qdrant client closed")
            self.client = None
            self._initialized = False

    def ping(self) -> bool:
        """Health check: verifies Qdrant is reachable."""
        try:
            client = self.get_client()
            # Use a lightweight operation like retrieving collections list
            client.get_collections()
            return True
        except Exception as e:
            logger.error(f"Qdrant ping failed: {e}")
            return False


# Global singleton instance (module-level)
qdrant_manager = QdrantManager()
