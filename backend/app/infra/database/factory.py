"""
Database / Vectorstore / Checkpointer / Store factory (singletons).

All business code calls these `get_xxx()` functions. The concrete backend
    (PostgreSQL/pgvector/AsyncPostgresStore for prod mode,
    SQLite/sqlite-vec/InMemoryStore for dev mode) is
selected based on `Settings.DATABASE_TYPE` / `Settings.VECTORSTORE_TYPE`.

Thread/coroutine safety:
    Singleton creation uses asyncio.Lock (init is now async). This is safe
    because every caller is in the async context (FastAPI handlers + lifespan).

    `get_xxx()` are sync to keep the call sites simple — they only return
    pre-created singletons. The actual creation happens inside `init_xxx()`,
    which is called from the FastAPI lifespan before any request is served.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Optional

from app.infra.config import get_settings
from app.infra.database.postgres import (
    PostgresCheckpointer,
    PostgresDatabase,
    PostgresStore,
    PGVectorVectorstore,
)
from app.infra.database.sqlite import (
    InMemoryStoreBackend,
    SQLiteDatabase,
    SqliteCheckpointer,
    SqliteVecVectorstore,
)

logger = logging.getLogger(__name__)


# ── Singleton instances ─────────────────────────────────────────────────────
_db_instance: Any | None = None
_vs_instance: Any | None = None
_cp_instance: Any | None = None
_store_instance: Any | None = None  # None | concrete store | _NO_STORE
_NO_STORE = object()  # Sentinel: store explicitly unavailable for this backend

# ── Async lock for safe singleton creation (init is async) ──────────────────
_init_lock = asyncio.Lock()


# ── Backend registries (DATABASE_TYPE / VECTORSTORE_TYPE → class) ───────────
_DB_BACKENDS: dict[str, type] = {
    "postgres": PostgresDatabase,
    "sqlite": SQLiteDatabase,
}

_VS_BACKENDS: dict[str, type] = {
    "pgvector": PGVectorVectorstore,
    "sqlite_vec": SqliteVecVectorstore,
}

_CP_BACKENDS: dict[str, type] = {
    "postgres": PostgresCheckpointer,
    "sqlite": SqliteCheckpointer,
}

_STORE_BACKENDS: dict[str, type] = {
    # LangGraph official best practice:
    #   - Prod mode (PostgreSQL): AsyncPostgresStore for durable long-term memory
    #   - Dev mode (SQLite):      InMemoryStore (ephemeral; SQLite not recommended for Store)
    "postgres": PostgresStore,
    "sqlite": InMemoryStoreBackend,
}


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


def get_database() -> Any:
    """Return the database singleton. `init_database()` must run during startup."""
    if _db_instance is None:
        raise RuntimeError(
            "Database not initialized. Ensure init_database() (or init_all()) "
            "was called during application startup."
        )
    return _db_instance


def get_vectorstore() -> Any:
    """Return the vectorstore singleton. `init_vectorstore()` must run during startup."""
    if _vs_instance is None:
        raise RuntimeError(
            "Vectorstore not initialized. Ensure init_vectorstore() (or init_all()) "
            "was called during application startup."
        )
    return _vs_instance


def get_checkpointer() -> Any:
    """Return the checkpointer singleton. `init_checkpointer()` must run during startup."""
    if _cp_instance is None:
        raise RuntimeError(
            "Checkpointer not initialized. Ensure init_checkpointer() (or init_all()) "
            "was called during application startup."
        )
    return _cp_instance


def get_store() -> Optional[Any]:
    """Return the long-term Store singleton, or None if unavailable for this backend."""
    if _store_instance is None:
        # Not yet initialized — caller may be checking before lifespan ran.
        return None
    if _store_instance is _NO_STORE:
        return None
    return _store_instance


def get_saver():
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
        settings = get_settings()
        db_type = settings.DATABASE_TYPE
        if db_type not in _DB_BACKENDS:
            raise ValueError(
                f"Unsupported DATABASE_TYPE: {db_type}. "
                f"Supported: {list(_DB_BACKENDS.keys())}"
            )
        instance = _DB_BACKENDS[db_type]()
        await instance.initialize()
        _db_instance = instance
        logger.info("Database initialized: %s", db_type)


async def init_vectorstore() -> None:
    """Initialize the vectorstore singleton (idempotent) with embedding function."""
    global _vs_instance
    async with _init_lock:
        if _vs_instance is not None:
            return
        settings = get_settings()
        vs_type = settings.VECTORSTORE_TYPE
        if vs_type not in _VS_BACKENDS:
            raise ValueError(
                f"Unsupported VECTORSTORE_TYPE: {vs_type}. "
                f"Supported: {list(_VS_BACKENDS.keys())}"
            )
        instance = _VS_BACKENDS[vs_type]()
        instance.set_embed_fn(_get_embed_fn())
        await instance.initialize()
        _vs_instance = instance
        logger.info("Vectorstore initialized: %s (with embedding function)", vs_type)


async def init_checkpointer() -> None:
    """Initialize the checkpointer singleton (idempotent)."""
    global _cp_instance
    async with _init_lock:
        if _cp_instance is not None:
            return
        settings = get_settings()
        db_type = settings.DATABASE_TYPE
        if db_type not in _CP_BACKENDS:
            raise ValueError(
                f"No checkpointer backend for DATABASE_TYPE: {db_type}. "
                f"Supported: {list(_CP_BACKENDS.keys())}"
            )
        instance = _CP_BACKENDS[db_type]()
        await instance.initialize()
        _cp_instance = instance
        logger.info("Checkpointer initialized: %s", db_type)


async def init_store() -> None:
    """Initialize the long-term Store singleton (idempotent).

    For prod mode (PostgreSQL): AsyncPostgresStore (persistent, with vector search if configured).
    For dev mode (SQLite):      InMemoryStore (ephemeral, dev/test only).
    """
    global _store_instance
    async with _init_lock:
        if _store_instance is not None:
            return
        settings = get_settings()
        db_type = settings.DATABASE_TYPE
        if db_type not in _STORE_BACKENDS:
            logger.warning(
                "Store not available for DATABASE_TYPE: %s. "
                "Supported: %s. Long-term memory disabled.",
                db_type,
                list(_STORE_BACKENDS.keys()),
            )
            _store_instance = _NO_STORE
            return
        instance = _STORE_BACKENDS[db_type]()
        await instance.initialize()
        _store_instance = instance
        logger.info("Store initialized: %s", db_type)


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
        store = _store_instance if _store_instance is not _NO_STORE else None
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
