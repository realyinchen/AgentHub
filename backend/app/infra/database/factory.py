"""
Database / Vectorstore / Checkpointer / Store factory (singletons).

All business code calls these ``get_xxx()`` functions. All components use
PostgreSQL + pgvector exclusively.

Thread/coroutine safety:
    Singleton creation uses asyncio.Lock (init is now async). This is safe
    because every caller is in the async context (FastAPI handlers + lifespan).

    ``get_xxx()`` are sync to keep the call sites simple — they only return
    pre-created singletons. The actual creation happens inside ``init_xxx()``,
    which is called from the FastAPI lifespan before any request is served.
"""

from __future__ import annotations

import asyncio
import logging

from langgraph.checkpoint.base import BaseCheckpointSaver

from app.infra.database.postgres import (
    PostgresCheckpointer,
    PostgresDatabase,
    PostgresStore,
    PGVectorVectorstore,
)

logger = logging.getLogger(__name__)

_db_instance: PostgresDatabase | None = None
_vs_instance: PGVectorVectorstore | None = None
_cp_instance: PostgresCheckpointer | None = None
_store_instance: PostgresStore | None = None

_init_lock = asyncio.Lock()




# ── Embedding function (lazy-resolves the current embedding model) ──────────
def _get_embed_fn():
    """Build a text→embedding async function backed by ModelManager.

    The function resolves the current embedding model on EVERY call, so a
    vectorstore created before any embedding model is configured still works
    once one is added. Raises ValueError if no model is configured at call time.
    """

    async def embed_fn(text: str) -> list[float]:
        import litellm
        from app.infra.llm.model_manager import get_model_manager

        model_id, api_key = await get_model_manager().get_embedding_model()
        if model_id is None:
            raise ValueError(
                "No embedding model configured. "
                "Please configure at least one Embedding model in settings."
            )
        response = await litellm.aembedding(
            model=model_id, input=[text], api_key=api_key
        )
        return response.data[0]["embedding"]

    return embed_fn


# ─────────────────────────────────────────────────────────────────────────────
# Public accessors (sync — return pre-created singletons)
# ─────────────────────────────────────────────────────────────────────────────


def get_database() -> PostgresDatabase:
    """Return the database singleton."""
    if _db_instance is None:
        raise RuntimeError("Database not initialized — call init_database() during startup")
    return _db_instance


def get_vectorstore() -> PGVectorVectorstore:
    """Return the vectorstore singleton."""
    if _vs_instance is None:
        raise RuntimeError("Vectorstore not initialized — call init_vectorstore() during startup")
    return _vs_instance


def get_checkpointer() -> PostgresCheckpointer:
    """Return the checkpointer singleton."""
    if _cp_instance is None:
        raise RuntimeError("Checkpointer not initialized — call init_checkpointer() during startup")
    return _cp_instance


def get_store() -> PostgresStore | None:
    """Return the long-term Store singleton, or None if not initialized."""
    return _store_instance


def get_saver() -> BaseCheckpointSaver:
    """Convenience: return the LangGraph-compatible saver from the checkpointer."""
    return get_checkpointer().get_saver()


# ─────────────────────────────────────────────────────────────────────────────
# Lifecycle: init / dispose (called by FastAPI lifespan)
# ─────────────────────────────────────────────────────────────────────────────


async def init_database() -> None:
    """Initialize the database singleton (idempotent)."""
    global _db_instance
    async with _init_lock:
        if _db_instance is not None:
            return
        instance = PostgresDatabase()
        await instance.initialize()
        _db_instance = instance
        logger.info("Database initialized: postgres")


async def init_vectorstore() -> None:
    """Initialize the vectorstore singleton (idempotent) with embedding function."""
    global _vs_instance
    async with _init_lock:
        if _vs_instance is not None:
            return
        instance = PGVectorVectorstore()
        instance.set_embed_fn(_get_embed_fn())
        await instance.initialize()
        _vs_instance = instance
        logger.info("Vectorstore initialized: pgvector (with embedding function)")


async def init_checkpointer() -> None:
    """Initialize the checkpointer singleton (idempotent)."""
    global _cp_instance
    async with _init_lock:
        if _cp_instance is not None:
            return
        instance = PostgresCheckpointer()
        await instance.initialize()
        _cp_instance = instance
        logger.info("Checkpointer initialized: postgres")


async def init_store() -> None:
    """Initialize the long-term Store singleton (idempotent).

    Uses AsyncPostgresStore for persistent long-term memory with
    optional vector search.
    """
    global _store_instance
    async with _init_lock:
        if _store_instance is not None:
            return
        instance = PostgresStore()
        await instance.initialize()
        _store_instance = instance
        logger.info("Store initialized: postgres")


async def init_all() -> None:
    """Initialize every backend component. Called during FastAPI startup."""
    await init_database()
    await init_vectorstore()
    await init_checkpointer()
    await init_store()


async def dispose_all() -> None:
    """Dispose every backend. Called during FastAPI shutdown.

    Dispose order: vectorstore → checkpointer → store → database (last,
    in case other backends depend on it).
    """
    global _db_instance, _vs_instance, _cp_instance, _store_instance

    async with _init_lock:
        vs, cp, db = _vs_instance, _cp_instance, _db_instance
        store = _store_instance
        _vs_instance = _cp_instance = _store_instance = _db_instance = None

    # Dispose outside the lock to avoid holding it during slow operations.
    if vs is not None:
        try:
            await vs.dispose()
            logger.info("Vectorstore disposed")
        except Exception as e:
            logger.warning("Error disposing vectorstore: %s", e)

    if cp is not None:
        try:
            await cp.dispose()
            logger.info("Checkpointer disposed")
        except Exception as e:
            logger.warning("Error disposing checkpointer: %s", e)

    if store is not None:
        try:
            await store.dispose()
            logger.info("Store disposed")
        except Exception as e:
            logger.warning("Error disposing store: %s", e)

    if db is not None:
        try:
            await db.dispose()
            logger.info("Database disposed")
        except Exception as e:
            logger.warning("Error disposing database: %s", e)


__all__ = [
    "get_database",
    "get_vectorstore",
    "get_checkpointer",
    "get_store",
    "get_saver",
    "init_database",
    "init_vectorstore",
    "init_checkpointer",
    "init_store",
    "init_all",
    "dispose_all",
]
