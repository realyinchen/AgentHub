"""
SQLite Store backend - InMemoryStore (development / testing).

Provides long-term memory (cross-session, cross-thread) for dev mode only.
NOT persisted - data is lost on process restart. Production uses postgres/store.py.
"""

from __future__ import annotations

import logging
from typing import Optional

from langgraph.store.memory import InMemoryStore

logger = logging.getLogger(__name__)


class InMemoryStoreBackend:
    """In-memory Store backend using LangGraph's official InMemoryStore.

    For DEVELOPMENT / TESTING ONLY — data is lost on process restart.
    """

    def __init__(self) -> None:
        self._store: InMemoryStore = InMemoryStore()

    async def initialize(self) -> None:
        logger.warning(
            "InMemoryStore initialized — long-term memory data IS NOT PERSISTED. "
            "Use PostgreSQL in production for durable storage."
        )

    def get_store(self) -> InMemoryStore:
        return self._store

    async def aput(
        self,
        namespace: tuple[str, ...],
        key: str,
        value: dict,
        index: Optional[list[str]] = None,
    ) -> None:
        self._store.put(namespace, key, value)

    async def aget(self, namespace: tuple[str, ...], key: str) -> Optional[dict]:
        item = self._store.get(namespace, key)
        return None if item is None else item.value

    async def asearch(
        self,
        namespace_prefix: tuple[str, ...],
        query: Optional[str] = None,
        limit: int = 10,
        filter: Optional[dict] = None,
    ) -> list[dict]:
        items = self._store.search(namespace_prefix, query=query, limit=limit)
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
        self._store.delete(namespace, key)

    async def dispose(self) -> None:
        logger.info("InMemoryStore disposed")
