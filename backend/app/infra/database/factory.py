"""
Database / Vectorstore / Checkpointer / Store factory (singletons).

All business code calls these ``get_xxx()`` functions. All components use
PostgreSQL + pgvector exclusively.

Lifecycle:
    - ``init_all()`` is called during FastAPI startup (lifespan).
    - ``dispose_all()`` is called during FastAPI shutdown.
    - ``get_xxx()`` returns pre-created singletons (sync, no async lock needed).
"""

from __future__ import annotations

import asyncio
import logging
from typing import Awaitable, Callable

from langgraph.checkpoint.base import BaseCheckpointSaver

from app.infra.database.database import PostgresDatabase
from app.infra.database.vectorstore import PGVectorVectorstore
from app.infra.database.checkpointer import PostgresCheckpointer
from app.infra.database.store import PostgresStore

logger = logging.getLogger(__name__)

# Singleton instances (created during startup, accessed via get_xxx())
_db_instance: PostgresDatabase | None = None
_vs_instance: PGVectorVectorstore | None = None
_cp_instance: PostgresCheckpointer | None = None
_store_instance: PostgresStore | None = None


# ── Embedding function for Vectorstore ──────────────────────────────────────


def _get_embed_fn() -> Callable[[str], Awaitable[list[float]]]:
    """Build a text→embedding async function backed by ModelManager.

    The function resolves the current embedding model on EVERY call, so a
    vectorstore created before any embedding model is configured still works
    once one is added.
    """

    async def embed_fn(text: str) -> list[float]:
        import litellm
        from app.infra.llm import get_model_manager

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


# ── Public accessors (sync — return pre-created singletons) ──────────────────


def get_database() -> PostgresDatabase:
    """Return the database singleton."""
    if _db_instance is None:
        raise RuntimeError("Database not initialized — call init_all() during startup")
    return _db_instance


def get_vectorstore() -> PGVectorVectorstore:
    """Return the vectorstore singleton."""
    if _vs_instance is None:
        raise RuntimeError(
            "Vectorstore not initialized — call init_all() during startup"
        )
    return _vs_instance


def get_checkpointer() -> PostgresCheckpointer:
    """Return the checkpointer singleton."""
    if _cp_instance is None:
        raise RuntimeError(
            "Checkpointer not initialized — call init_all() during startup"
        )
    return _cp_instance


def get_store() -> PostgresStore | None:
    """Return the long-term Store singleton, or None if not initialized."""
    return _store_instance


def get_saver() -> BaseCheckpointSaver:
    """Convenience: return the LangGraph-compatible saver from the checkpointer."""
    return get_checkpointer().get_saver()


# ── Lifecycle: init / dispose (called by FastAPI lifespan) ───────────────────


async def init_all() -> None:
    """Initialize all database components. Called during FastAPI startup.

    Order: database first (others may depend on it), then vectorstore,
    checkpointer, store in parallel.
    """
    global _db_instance, _vs_instance, _cp_instance, _store_instance

    # Database must be initialized first
    _db_instance = PostgresDatabase()
    await _db_instance.initialize()
    logger.info("Database initialized: postgres")

    # Initialize vectorstore with embedding function
    _vs_instance = PGVectorVectorstore()
    _vs_instance.set_embed_fn(_get_embed_fn())
    await _vs_instance.initialize()
    logger.info("Vectorstore initialized: pgvector (with embedding function)")

    # Initialize checkpointer and store in parallel
    async def _init_checkpointer() -> None:
        global _cp_instance
        _cp_instance = PostgresCheckpointer()
        await _cp_instance.initialize()
        logger.info("Checkpointer initialized: postgres")

    async def _init_store() -> None:
        global _store_instance
        _store_instance = PostgresStore()
        await _store_instance.initialize()
        logger.info("Store initialized: postgres")

    await asyncio.gather(_init_checkpointer(), _init_store())


async def dispose_all() -> None:
    """Dispose all database components. Called during FastAPI shutdown.

    Order: vectorstore → checkpointer → store → database (last,
    in case other backends depend on it).
    """
    global _db_instance, _vs_instance, _cp_instance, _store_instance

    # Clear singleton references first
    vs, cp, store, db = _vs_instance, _cp_instance, _store_instance, _db_instance
    _vs_instance = _cp_instance = _store_instance = _db_instance = None

    # Dispose in reverse order
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
    "init_all",
    "dispose_all",
]
