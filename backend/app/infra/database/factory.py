"""
Database / Vectorstore / Checkpointer / Store factory (singletons).

All business code calls these ``get_xxx()`` functions. All components use
PostgreSQL + pgvector exclusively.

Lifecycle:
    - ``init_database()`` is called during FastAPI startup (lifespan).
    - ``dispose_database()`` is called during FastAPI shutdown.
    - ``get_xxx()`` returns pre-created singletons (sync, no async lock needed).

Embedding functions are provided by infra.llm.embedding module (singleton
LiteLLMEmbeddings instance created at startup).

Multi-table vectorstore support:
    - ``get_vectorstore(table_name)`` returns instance for specific collection.
    - Default table: "langchain_pg_embedding"
    - Additional tables are lazily initialized on first access.
"""

import asyncio
import logging

from langgraph.checkpoint.base import BaseCheckpointSaver

from app.infra.database.database import PostgresDatabase
from app.infra.database.vectorstore import PGVectorVectorstore, _DEFAULT_TABLE
from app.infra.database.checkpointer import PostgresCheckpointer
from app.infra.database.store import PostgresStore

logger = logging.getLogger(__name__)

# Singleton instances (created during startup, accessed via get_xxx())
_db_instance: PostgresDatabase | None = None
_cp_instance: PostgresCheckpointer | None = None
_store_instance: PostgresStore | None = None

# Multi-table vectorstore cache: table_name -> PGVectorVectorstore instance
_vs_instances: dict[str, PGVectorVectorstore] = {}


# ── Public accessors (sync — return pre-created singletons) ──────────────────


def get_database() -> PostgresDatabase:
    """Return the database singleton."""
    if _db_instance is None:
        raise RuntimeError(
            "Database not initialized — call init_database() during startup"
        )
    return _db_instance


def get_vectorstore(table_name: str = _DEFAULT_TABLE) -> PGVectorVectorstore:
    """Return the vectorstore instance for the specified table.

    Args:
        table_name: PostgreSQL table name for storing vectors.
                   Defaults to 'langchain_pg_embedding'.

    Returns:
        PGVectorVectorstore instance bound to the specified table.

    Note:
        Default table is initialized during startup. Additional tables
        are lazily initialized on first access (requires async context).
        For lazy initialization, use get_or_create_vectorstore() instead.
    """
    if table_name not in _vs_instances:
        if table_name == _DEFAULT_TABLE:
            raise RuntimeError(
                "Default vectorstore not initialized — call init_database() during startup"
            )
        # For non-default tables, suggest using async version
        raise RuntimeError(
            f"Vectorstore table '{table_name}' not initialized. "
            f"Use get_or_create_vectorstore() for lazy initialization."
        )
    return _vs_instances[table_name]


async def get_or_create_vectorstore(
    table_name: str = _DEFAULT_TABLE,
) -> PGVectorVectorstore:
    """Get or create vectorstore instance for the specified table.

    Lazily initializes vectorstore for tables other than the default.
    The default table is initialized during startup via init_database().

    Args:
        table_name: PostgreSQL table name for storing vectors.

    Returns:
        PGVectorVectorstore instance bound to the specified table.
    """
    if table_name in _vs_instances:
        return _vs_instances[table_name]

    # Lazily create new vectorstore instance
    from app.infra.llm import get_embeddings

    logger.info("Lazily initializing vectorstore for table '%s'", table_name)
    vs = PGVectorVectorstore(table_name=table_name)
    vs.set_embed_fn(embeddings=get_embeddings())
    await vs.initialize()

    _vs_instances[table_name] = vs
    logger.info("Vectorstore initialized for table '%s'", table_name)
    return vs


def get_checkpointer() -> PostgresCheckpointer:
    """Return the checkpointer singleton."""
    if _cp_instance is None:
        raise RuntimeError(
            "Checkpointer not initialized — call init_database() during startup"
        )
    return _cp_instance


def get_store() -> PostgresStore | None:
    """Return the long-term Store singleton, or None if not initialized."""
    return _store_instance


def get_saver() -> BaseCheckpointSaver:
    """Convenience: return the LangGraph-compatible saver from the checkpointer."""
    return get_checkpointer().get_saver()


# ── Lifecycle: init / dispose (called by FastAPI lifespan) ───────────────────


async def init_database() -> None:
    """Initialize all database components. Called during FastAPI startup.

    Order: database first (others may depend on it), then vectorstore,
    checkpointer, store in parallel.

    Note: Embedding functions are provided by infra.llm.embedding module.
    Call init_embedding_model() in main.py lifespan BEFORE init_database() to
    ensure embedding functions are available.
    """
    global _db_instance, _cp_instance, _store_instance, _vs_instances

    # Database must be initialized first
    _db_instance = PostgresDatabase()
    await _db_instance.initialize()
    logger.info("Database initialized: postgres")

    # Initialize default vectorstore only when an embedding model is configured.
    # Book search and structured preference memory do not require embeddings, so
    # local-only setups such as LM Studio can still boot without semantic search.
    from app.infra.llm import get_embeddings

    embeddings = get_embeddings()
    if embeddings is not None:
        default_vs = PGVectorVectorstore(table_name=_DEFAULT_TABLE)
        default_vs.set_embed_fn(embeddings=embeddings)
        await default_vs.initialize()
        _vs_instances[_DEFAULT_TABLE] = default_vs
        logger.info("Vectorstore initialized: pgvector (table=%s)", _DEFAULT_TABLE)
    else:
        logger.warning(
            "Embedding model not configured; default vectorstore is disabled"
        )

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


async def dispose_database() -> None:
    """Dispose all database components. Called during FastAPI shutdown.

    Order: vectorstores → checkpointer → store → database (last,
    in case other backends depend on it).
    """
    global _db_instance, _cp_instance, _store_instance, _vs_instances

    # Clear singleton references first
    vs_instances = _vs_instances.copy()
    _vs_instances.clear()

    cp, store, db = _cp_instance, _store_instance, _db_instance
    _cp_instance = _store_instance = _db_instance = None

    # Dispose all vectorstores
    for table_name, vs in vs_instances.items():
        try:
            await vs.dispose()
            logger.info("Vectorstore disposed (table=%s)", table_name)
        except Exception as e:
            logger.warning("Error disposing vectorstore (table=%s): %s", table_name, e)

    # Dispose checkpointer
    if cp is not None:
        try:
            await cp.dispose()
            logger.info("Checkpointer disposed")
        except Exception as e:
            logger.warning("Error disposing checkpointer: %s", e)

    # Dispose store
    if store is not None:
        try:
            await store.dispose()
            logger.info("Store disposed")
        except Exception as e:
            logger.warning("Error disposing store: %s", e)

    # Dispose database (last)
    if db is not None:
        try:
            await db.dispose()
            logger.info("Database disposed")
        except Exception as e:
            logger.warning("Error disposing database: %s", e)


__all__ = [
    "get_database",
    "get_vectorstore",
    "get_or_create_vectorstore",
    "get_checkpointer",
    "get_store",
    "get_saver",
    "init_database",
    "dispose_database",
]
