"""Embedding model management for AgentHub.

Provides a singleton LiteLLMEmbeddings instance initialized at startup.
All embedding calls use the same cached instance - zero model re-initialization.

Used by: Store, Vectorstore, RAG Agent, and other semantic search components.

Configuration (from .env):
    SYSTEM_DEFAULT_EMBEDDING_MODEL=provider/model-id (e.g. "openai/text-embedding-3-small")
    EMBEDDING_DIMENSION=1536
    SYSTEM_DEFAULT_LLM_API_KEY (shared with embedding)
"""

from __future__ import annotations

import logging

import litellm
from langchain_core.embeddings import Embeddings

from app.infra.config import get_settings

logger = logging.getLogger(__name__)


class LiteLLMEmbeddings(Embeddings):
    """LiteLLM-backed Embeddings class following LangChain's standard interface.

    Created once at startup, reused for all embedding calls.
    No per-call model re-initialization overhead.

    LangChain Embeddings interface:
        - embed_documents(texts: list[str]) -> list[list[float]]  (sync)
        - embed_query(text: str) -> list[float]                   (sync)
        - aembed_documents(texts: list[str]) -> list[list[float]] (async)
        - aembed_query(text: str) -> list[float]                  (async)
    """

    def __init__(self, model: str, api_key: str | None = None):
        self.model = model
        self.api_key = api_key

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """Sync embed - not recommended, use aembed_documents instead."""
        raise NotImplementedError(
            "Use aembed_documents() for async embedding. "
            "LiteLLM's sync embedding may block in async context."
        )

    def embed_query(self, text: str) -> list[float]:
        """Sync embed - not recommended, use aembed_query instead."""
        raise NotImplementedError(
            "Use aembed_query() for async embedding. "
            "LiteLLM's sync embedding may block in async context."
        )

    async def aembed_documents(self, texts: list[str]) -> list[list[float]]:
        """Async embed multiple texts using cached LiteLLM instance."""
        response = await litellm.aembedding(
            model=self.model,
            input=texts,
            api_key=self.api_key,
        )
        return [item["embedding"] for item in response.data]

    async def aembed_query(self, text: str) -> list[float]:
        """Async embed single query using cached LiteLLM instance."""
        response = await litellm.aembedding(
            model=self.model,
            input=[text],
            api_key=self.api_key,
        )
        return response.data[0]["embedding"]


# ── Singleton instance (created once at startup) ─────────────────────────────

_embeddings_instance: LiteLLMEmbeddings | None = None


def init_embedding_model() -> None:
    """Initialize embedding model instance from .env configuration.

    Called ONCE during FastAPI lifespan startup.
    Creates a LiteLLMEmbeddings instance that is reused for all calls.

    Example .env:
        SYSTEM_DEFAULT_EMBEDDING_MODEL=openai/text-embedding-3-small
        EMBEDDING_DIMENSION=1536
        SYSTEM_DEFAULT_LLM_API_KEY=sk-xxx
    """
    global _embeddings_instance

    settings = get_settings()

    if settings.SYSTEM_DEFAULT_EMBEDDING_MODEL is None:
        logger.warning(
            "SYSTEM_DEFAULT_EMBEDDING_MODEL not configured in .env. "
            "Vector search and long-term memory will be unavailable."
        )
        return

    # Create the singleton LiteLLMEmbeddings instance
    _embeddings_instance = LiteLLMEmbeddings(
        model=settings.SYSTEM_DEFAULT_EMBEDDING_MODEL,
        api_key=settings.system_default_embedding_api_key,
    )

    logger.info(
        "Embedding model instance created: %s (dims=%d)",
        settings.SYSTEM_DEFAULT_EMBEDDING_MODEL,
        settings.EMBEDDING_DIMENSION,
    )


def get_embeddings() -> LiteLLMEmbeddings | None:
    """Return the cached LiteLLMEmbeddings instance.

    The instance was created once at startup.
    All calls reuse the same instance - zero model re-initialization.

    Returns:
        LiteLLMEmbeddings instance, or None if not configured.

    Usage:
        embeddings = get_embeddings()
        if embeddings:
            vector = await embeddings.aembed_query("hello")
    """
    return _embeddings_instance


__all__ = [
    "LiteLLMEmbeddings",
    "init_embedding_model",
    "get_embeddings",
]
