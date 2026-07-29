"""Lifecycle and accessors for PostgreSQL infrastructure singletons."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from langgraph.checkpoint.base import BaseCheckpointSaver

from app.infra.database.checkpointer import PostgresCheckpointer
from app.infra.database.database import PostgresDatabase
from app.infra.database.store import PostgresStore
from app.infra.database.vectorstore import PGVectorVectorstore, _DEFAULT_TABLE
if TYPE_CHECKING:
    from app.infra.embedding_spaces.runtime import EmbeddingSpaceRuntime

logger = logging.getLogger(__name__)

_db_instance: PostgresDatabase | None = None
_cp_instance: PostgresCheckpointer | None = None
_store_instance: PostgresStore | None = None
_embedding_space_runtime: EmbeddingSpaceRuntime | None = None
_vs_instances: dict[str, PGVectorVectorstore] = {}


def get_database() -> PostgresDatabase:
    if _db_instance is None:
        raise RuntimeError(
            "Database not initialized; call init_database() during startup"
        )
    return _db_instance


def get_embedding_space_runtime() -> EmbeddingSpaceRuntime:
    if _embedding_space_runtime is None:
        raise RuntimeError("Embedding-space runtime is not initialized")
    return _embedding_space_runtime


def get_vectorstore(table_name: str = _DEFAULT_TABLE) -> PGVectorVectorstore:
    """Resolve the logical default to its atomically active generation."""

    if table_name == _DEFAULT_TABLE:
        return get_embedding_space_runtime().get_active_store("documents")
    if table_name not in _vs_instances:
        raise RuntimeError(
            f"Vectorstore table {table_name!r} is not initialized; "
            "use get_or_create_vectorstore()"
        )
    return _vs_instances[table_name]


async def get_or_create_vectorstore(
    table_name: str = _DEFAULT_TABLE,
) -> PGVectorVectorstore:
    if table_name == _DEFAULT_TABLE:
        return get_vectorstore()
    if table_name in _vs_instances:
        return _vs_instances[table_name]

    from app.infra.llm.embedding import get_persistent_embeddings

    embeddings = get_persistent_embeddings()
    if embeddings is None:
        raise RuntimeError(
            "Persistent vectorstore is unavailable until the embedding "
            "provider returns a valid vector"
        )
    vectorstore = PGVectorVectorstore(
        table_name=table_name,
        database=get_database(),
    )
    vectorstore.set_embed_fn(embeddings=embeddings)
    await vectorstore.initialize()
    _vs_instances[table_name] = vectorstore
    return vectorstore


def get_checkpointer() -> PostgresCheckpointer:
    if _cp_instance is None:
        raise RuntimeError(
            "Checkpointer not initialized; call init_database() during startup"
        )
    return _cp_instance


def get_store() -> PostgresStore | None:
    return _store_instance


def get_saver() -> BaseCheckpointSaver:
    return get_checkpointer().get_saver()


async def init_database_connection() -> None:
    global _db_instance
    if _db_instance is not None:
        logger.warning("Database connection already initialized, skipping")
        return
    _db_instance = PostgresDatabase()
    await _db_instance.initialize()
    logger.info("Database initialized: postgres")


async def init_database_components() -> None:
    """Initialize dependants without waiting for vector generation builds."""

    global _cp_instance, _store_instance, _embedding_space_runtime

    if _db_instance is None:
        raise RuntimeError(
            "Database connection is not initialized; "
            "call init_database_connection() first"
        )
    if (
        _cp_instance is not None
        or _store_instance is not None
        or _embedding_space_runtime is not None
    ):
        if (
            _cp_instance is not None
            and _store_instance is not None
            and _embedding_space_runtime is not None
        ):
            logger.warning("Database components already initialized, skipping")
            return
        raise RuntimeError(
            "Database components are partially initialized; dispose them "
            "before retrying startup"
        )

    from app.infra.llm.embedding import (
        get_active_embedding_config,
        get_embeddings,
    )

    from app.infra.embedding_spaces.runtime import EmbeddingSpaceRuntime

    _embedding_space_runtime = EmbeddingSpaceRuntime(_db_instance)
    _embedding_space_runtime.start(
        config=get_active_embedding_config(),
        embeddings=get_embeddings(),
    )
    logger.info(
        "Embedding-space runtime initialized; generation builds are asynchronous"
    )

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


async def init_database() -> None:
    """Backward-compatible full startup in canonical dependency order."""

    await init_database_connection()

    from app.infra.llm.embedding import (
        initialize_embedding_runtime,
        probe_embedding_runtime,
    )
    from app.infra.llm.manager import get_model_manager

    manager = get_model_manager()
    if not getattr(manager, "_initialized", False):
        await manager.refresh()
    config = initialize_embedding_runtime()
    if config is not None:
        await probe_embedding_runtime(config)
    await init_database_components()


async def dispose_database() -> None:
    """Dispose embedding spaces before their shared database connection."""

    global _db_instance, _cp_instance, _store_instance
    global _embedding_space_runtime, _vs_instances

    vectorstores = _vs_instances.copy()
    _vs_instances.clear()
    embedding_spaces = _embedding_space_runtime
    checkpointer = _cp_instance
    store = _store_instance
    database = _db_instance
    _embedding_space_runtime = None
    _cp_instance = None
    _store_instance = None
    _db_instance = None

    if embedding_spaces is not None:
        try:
            await embedding_spaces.dispose()
        except Exception as exc:
            logger.warning("Error disposing embedding spaces: %s", exc)

    for table_name, vectorstore in vectorstores.items():
        try:
            await vectorstore.dispose()
        except Exception as exc:
            logger.warning(
                "Error disposing vectorstore (table=%s): %s",
                table_name,
                exc,
            )

    if checkpointer is not None:
        try:
            await checkpointer.dispose()
        except Exception as exc:
            logger.warning("Error disposing checkpointer: %s", exc)
    if store is not None:
        try:
            await store.dispose()
        except Exception as exc:
            logger.warning("Error disposing store: %s", exc)
    if database is not None:
        try:
            await database.dispose()
        except Exception as exc:
            logger.warning("Error disposing database: %s", exc)

    from app.infra.llm.embedding import reset_embedding_runtime

    reset_embedding_runtime()
    logger.info("Database and embedding runtimes disposed")


__all__ = [
    "dispose_database",
    "get_checkpointer",
    "get_database",
    "get_embedding_space_runtime",
    "get_or_create_vectorstore",
    "get_saver",
    "get_store",
    "get_vectorstore",
    "init_database",
    "init_database_components",
    "init_database_connection",
]
