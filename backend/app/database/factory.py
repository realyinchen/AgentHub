"""
Database and Vectorstore Factory Module

Creates configuration-driven database and vectorstore instances.
All business code should use get_database() / get_vectorstore() to obtain instances.
"""

import logging
from typing import Optional

from app.core.config import settings
from app.database.interfaces import (
    DatabaseInterface,
    VectorstoreInterface,
    CheckpointInterface,
)

logger = logging.getLogger(__name__)

# ── Cached singleton instances ──────────────────────────────────────────
_db_instance: Optional[DatabaseInterface] = None
_vs_instance: Optional[VectorstoreInterface] = None
_cp_instance: Optional[CheckpointInterface] = None

# ── Backend import paths (lazy import to avoid circular deps) ──────────
_DB_BACKENDS = {
    "postgres": "app.database.backends.postgres.db.PostgresDatabase",
    "sqlite": "app.database.backends.sqlite.db.SQLiteDatabase",
}

_VS_BACKENDS = {
    "qdrant": "app.database.backends.postgres.vectorstore.QdrantVectorstore",
}

_CP_BACKENDS = {
    "postgres": "app.database.backends.postgres.checkpointer.PostgresCheckpointer",
    "sqlite": "app.database.backends.sqlite.checkpointer.SqliteCheckpointer",
}


def _import_class(dotted_path: str):
    """Lazy import a class from a dotted module path."""
    module_path, class_name = dotted_path.rsplit(".", 1)
    import importlib

    module = importlib.import_module(module_path)
    return getattr(module, class_name)


def get_database() -> DatabaseInterface:
    """
    Get the database instance (singleton).

    Creates the instance on first call based on DATABASE_TYPE setting.
    Subsequent calls return the cached instance.
    """
    global _db_instance
    if _db_instance is None:
        db_type = settings.DATABASE_TYPE
        if db_type not in _DB_BACKENDS:
            raise ValueError(
                f"Unsupported DATABASE_TYPE: {db_type}. "
                f"Supported: {list(_DB_BACKENDS.keys())}"
            )
        cls = _import_class(_DB_BACKENDS[db_type])
        _db_instance = cls()
        logger.info(f"Created database instance: {db_type}")
    assert _db_instance is not None
    return _db_instance


def get_vectorstore() -> VectorstoreInterface:
    """
    Get the vectorstore instance (singleton).

    Creates the instance on first call based on VECTORSTORE_TYPE setting.
    If VECTORSTORE_TYPE is not set, defaults based on DATABASE_TYPE.
    """
    global _vs_instance
    if _vs_instance is None:
        vs_type = settings.VECTORSTORE_TYPE
        if vs_type not in _VS_BACKENDS:
            raise ValueError(
                f"Unsupported VECTORSTORE_TYPE: {vs_type}. "
                f"Supported: {list(_VS_BACKENDS.keys())}"
            )
        cls = _import_class(_VS_BACKENDS[vs_type])
        _vs_instance = cls()
        logger.info(f"Created vectorstore instance: {vs_type}")
    assert _vs_instance is not None
    return _vs_instance


def get_checkpointer() -> CheckpointInterface:
    """
    Get the checkpointer instance (singleton).

    Creates the instance on first call based on DATABASE_TYPE setting.
    """
    global _cp_instance
    if _cp_instance is None:
        db_type = settings.DATABASE_TYPE
        if db_type not in _CP_BACKENDS:
            raise ValueError(
                f"No checkpointer backend for DATABASE_TYPE: {db_type}. "
                f"Supported: {list(_CP_BACKENDS.keys())}"
            )
        cls = _import_class(_CP_BACKENDS[db_type])
        _cp_instance = cls()
        logger.info(f"Created checkpointer instance: {db_type}")
    assert _cp_instance is not None
    return _cp_instance


def get_saver():
    """
    Get the LangGraph checkpointer saver instance.

    Convenience function that delegates to the checkpointer.
    Returns the actual AsyncPostgresSaver / SqliteSaver object.
    """
    return get_checkpointer().get_saver()


async def init_database() -> None:
    """Initialize the database (create tables if needed)."""
    db = get_database()
    await db.initialize()
    logger.info("Database initialized")


async def init_vectorstore() -> None:
    """Initialize the vectorstore (connect to backend, create collection if needed)."""
    vs = get_vectorstore()
    await vs.initialize()
    logger.info("Vectorstore initialized")


async def init_checkpointer() -> None:
    """Initialize the checkpointer (create tables if needed)."""
    cp = get_checkpointer()
    await cp.initialize()
    logger.info("Checkpointer initialized")


async def init_all() -> None:
    """Initialize all backend components. Called during app startup."""
    await init_database()
    await init_vectorstore()
    await init_checkpointer()


async def dispose_all() -> None:
    """Dispose all backend components. Called during app shutdown."""
    global _db_instance, _vs_instance, _cp_instance

    if _vs_instance is not None:
        await _vs_instance.dispose()
        _vs_instance = None
        logger.info("Vectorstore disposed")

    if _cp_instance is not None:
        await _cp_instance.dispose()
        _cp_instance = None
        logger.info("Checkpointer disposed")

    if _db_instance is not None:
        await _db_instance.dispose()
        _db_instance = None
        logger.info("Database disposed")
