from qdrant_client import QdrantClient

from app.core.config import settings


# Global variable (module-level singleton)
_qdrant_client: QdrantClient | None = None


def validate_qdrant_config() -> None:
    """
    Validate that all required Qdrant configuration is present.
    Raises ValueError if any required configuration is missing.
    """
    required_vars = [
        "QDRANT_HOST",
        "QDRANT_PORT",
    ]

    missing = [var for var in required_vars if not getattr(settings, var, None)]
    if missing:
        raise ValueError(
            f"Missing required Qdrant configuration: {', '.join(missing)}. "
            "These environment variables must be set to use Qdrant vector store."
        )


def initialize_qdrant_client():
    """
    Initialize the global Qdrant client.

    Can be called explicitly during startup, or will be called lazily on first use.
    Raises RuntimeError if initialization fails.
    """
    validate_qdrant_config()
    global _qdrant_client
    if _qdrant_client is not None:
        return  # Already initialized

    try:
        _qdrant_client = QdrantClient(
            host=settings.QDRANT_HOST, port=settings.QDRANT_PORT
        )
    except Exception as e:
        _qdrant_client = None
        raise RuntimeError(f"Failed to initialize Qdrant client: {e}") from e


def close_qdrant_client():
    """Close the global Qdrant client."""
    global _qdrant_client
    if _qdrant_client:
        _qdrant_client.close()
        _qdrant_client = None


def get_qdrant_client() -> QdrantClient:
    """
    Get the global Qdrant client.

    If not initialized, attempt to initialize it first.
    Raises RuntimeError if initialization fails.
    """
    global _qdrant_client
    if _qdrant_client is None:
        initialize_qdrant_client()
    return _qdrant_client  # pyright: ignore[reportReturnType]
