"""
PostgreSQL Store backend (LangGraph AsyncPostgresStore).

Provides long-term memory (cross-session, cross-thread) with optional
vector semantic search. Enables agents to remember user preferences
and facts across conversations.
"""

from __future__ import annotations

import logging
from typing import (
    AsyncContextManager,
    Optional,
    Sequence,
    cast,
)

from langgraph.store.postgres.aio import AsyncPostgresStore
from langgraph.store.postgres.base import PostgresIndexConfig

from app.infra.config import get_settings

logger = logging.getLogger(__name__)


class PostgresStore:
    """
    PostgreSQL Store backend using LangGraph AsyncPostgresStore.

    Provides long-term memory with optional vector semantic search.
    Vector search is enabled when an embedding model is configured.
    """

    def __init__(self) -> None:
        self._store: AsyncPostgresStore | None = None
        self._cm: AsyncContextManager[AsyncPostgresStore] | None = None

    async def initialize(self) -> None:
        if self._store is not None:
            logger.warning("Store already initialized, skipping")
            return

        settings = get_settings()
        conn_string = settings.get_postgres_libpq_url()
        index_config = await self._try_build_index_config()

        if index_config is not None:
            self._cm = AsyncPostgresStore.from_conn_string(
                conn_string, index=index_config
            )
            logger.info(
                "PostgreSQL Store initialized with vector index (dims=%d)",
                index_config.get("dims", 0),
            )
        else:
            self._cm = AsyncPostgresStore.from_conn_string(conn_string)
            logger.info(
                "PostgreSQL Store initialized without vector index "
                "(no embedding model configured)"
            )

        self._store = await self._cm.__aenter__()
        await self._store.setup()

    async def _try_build_index_config(self) -> Optional[PostgresIndexConfig]:
        """Build vector-search index config if an embedding model is available."""
        try:
            from app.infra.llm.model_manager import get_model_manager

            model_id, _ = await get_model_manager().get_embedding_model()
            if model_id is None:
                return None

            dims = await self._probe_embedding_dims()

            async def embed_texts(texts: Sequence[str]) -> list[list[float]]:
                import litellm
                from app.infra.llm.model_manager import get_model_manager as _gmm

                m_id, api_key = await _gmm().get_embedding_model()
                if m_id is None:
                    raise ValueError("No embedding model configured")
                response = await litellm.aembedding(
                    model=m_id, input=list(texts), api_key=api_key
                )
                return [item["embedding"] for item in response.data]

            return cast(
                PostgresIndexConfig,
                {"dims": dims, "embed": embed_texts, "fields": ["$"]},
            )
        except Exception as e:
            logger.warning(
                "Failed to build Store vector index config: %s. "
                "Store will operate without semantic search.",
                e,
            )
            return None

    async def _probe_embedding_dims(self) -> int:
        """Detect embedding dimensions by calling the embedding model."""
        try:
            import litellm
            from app.infra.llm.model_manager import get_model_manager

            model_id, api_key = await get_model_manager().get_embedding_model()
            if model_id is None:
                return 1536
            response = await litellm.aembedding(
                model=model_id, input=["probe"], api_key=api_key
            )
            return len(response.data[0]["embedding"])
        except Exception as e:
            logger.warning("Could not probe embedding dims, defaulting to 1536: %s", e)
            return 1536

    def get_store(self) -> AsyncPostgresStore:
        if self._store is None:
            raise RuntimeError("Store not initialized. Call initialize() first.")
        return self._store

    async def aput(
        self,
        namespace: tuple[str, ...],
        key: str,
        value: dict,
        index: Optional[list[str]] = None,
    ) -> None:
        if self._store is None:
            raise RuntimeError("Store not initialized")
        await self._store.aput(namespace, key, value, index=index)

    async def aget(self, namespace: tuple[str, ...], key: str) -> Optional[dict]:
        if self._store is None:
            raise RuntimeError("Store not initialized")
        item = await self._store.aget(namespace, key)
        return None if item is None else item.value

    async def asearch(
        self,
        namespace_prefix: tuple[str, ...],
        query: Optional[str] = None,
        limit: int = 10,
        filter: Optional[dict] = None,
    ) -> list[dict]:
        if self._store is None:
            raise RuntimeError("Store not initialized")
        items = await self._store.asearch(
            namespace_prefix, query=query, limit=limit, filter=filter
        )
        return [
            {
                "namespace": list(item.namespace),
                "key": item.key,
                "value": item.value,
                "score": getattr(item, "score", None),
                "created_at": getattr(item, "created_at", None),
                "updated_at": getattr(item, "updated_at", None),
            }
            for item in items
        ]

    async def adelete(self, namespace: tuple[str, ...], key: str) -> None:
        if self._store is None:
            raise RuntimeError("Store not initialized")
        await self._store.adelete(namespace, key)

    async def dispose(self) -> None:
        if self._cm is not None:
            try:
                await self._cm.__aexit__(None, None, None)
            except Exception as e:
                logger.warning("Error disposing Store: %s", e)
            finally:
                self._store = None
                self._cm = None
                logger.info("PostgreSQL Store disposed")
