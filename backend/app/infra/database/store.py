"""PostgreSQL Store backend (LangGraph AsyncPostgresStore).

Provides the LangGraph structured key/value store. Semantic projections are
deliberately excluded because LangGraph's built-in ``store_vectors`` table has
one process-global fixed dimension. App-owned memory retrieval and versioned
embedding projections have independent lifecycles.

Reference:
https://docs.langchain.com/oss/python/langchain/long-term-memory
"""

import logging
from typing import AsyncContextManager, Optional

from langgraph.store.postgres.aio import AsyncPostgresStore

from app.infra.config import get_settings
from app.infra.errors import StoreError

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
        """Initialize the store connection and create tables.

        Uses AsyncPostgresStore.from_conn_string context manager pattern
        with optional vector index for semantic search.
        """
        if self._store is not None:
            logger.warning("Store already initialized, skipping")
            return

        settings = get_settings()
        conn_string = settings.get_postgres_conn_string()
        try:
            self._cm = AsyncPostgresStore.from_conn_string(conn_string)
            logger.info(
                "PostgreSQL Store initialized as structured storage; semantic "
                "vectors are managed by versioned embedding spaces"
            )

            self._store = await self._cm.__aenter__()
            await self._store.setup()
        except Exception as e:
            raise StoreError(
                f"Failed to initialize store: {e}",
                operation="initialize",
            ) from e

    def get_store(self) -> AsyncPostgresStore:
        """Return the LangGraph-compatible store."""
        if self._store is None:
            raise StoreError(
                "Store not initialized. Call initialize() first.",
                operation="get_store",
            )
        return self._store

    async def aput(
        self,
        namespace: tuple[str, ...],
        key: str,
        value: dict,
        index: Optional[list[str]] = None,
    ) -> None:
        """Store a value in the given namespace."""
        if self._store is None:
            raise StoreError(
                "Store not initialized",
                namespace=namespace,
                key=key,
                operation="aput",
            )
        await self._store.aput(namespace, key, value, index=index)

    async def aget(self, namespace: tuple[str, ...], key: str) -> Optional[dict]:
        """Retrieve a value by namespace and key."""
        if self._store is None:
            raise StoreError(
                "Store not initialized",
                namespace=namespace,
                key=key,
                operation="aget",
            )
        item = await self._store.aget(namespace, key)
        return None if item is None else item.value

    async def asearch(
        self,
        namespace_prefix: tuple[str, ...],
        query: Optional[str] = None,
        limit: int = 10,
        filter: Optional[dict] = None,
    ) -> list[dict]:
        """Search for items in the store."""
        if self._store is None:
            raise StoreError(
                "Store not initialized",
                namespace=namespace_prefix,
                operation="asearch",
            )
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
        """Delete an item from the store."""
        if self._store is None:
            raise StoreError(
                "Store not initialized",
                namespace=namespace,
                key=key,
                operation="adelete",
            )
        await self._store.adelete(namespace, key)

    async def dispose(self) -> None:
        """Dispose the store connection.

        Uses graceful cleanup: attempts normal exit first, then forced cleanup
        on any remaining resources. Safe to call multiple times.
        """
        if self._cm is None:
            return

        # Clear references first to prevent reuse during cleanup
        cm = self._cm
        self._store = None
        self._cm = None

        try:
            await cm.__aexit__(None, None, None)
            logger.info("PostgreSQL Store disposed")
        except Exception as e:
            # Log but don't raise - cleanup should be best-effort
            logger.warning("Error disposing Store (cleanup continued): %s", e)
            # Ensure resources are released even on error
            try:
                # Force cleanup with exception context
                exc_info = (type(e), e, e.__traceback__)
                await cm.__aexit__(*exc_info)
            except Exception:
                pass  # Ignore nested cleanup errors
            finally:
                logger.info("PostgreSQL Store disposed (with cleanup warnings)")
