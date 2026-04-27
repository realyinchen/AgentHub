"""
Database and Vectorstore Factory Module

Creates configuration-driven database and vectorstore instances.
All business code should use get_database() / get_vectorstore() to obtain instances.
"""

import logging
import threading
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

# ── Lock for thread-safe singleton creation (double-check locking) ──────
_singleton_lock = threading.Lock()

# ── Backend import paths (lazy import to avoid circular deps) ──────────
_DB_BACKENDS = {
    "postgres": "app.database.backends.postgres.db.PostgresDatabase",
    "sqlite": "app.database.backends.sqlite.db.SQLiteDatabase",
}

_VS_BACKENDS = {
    "qdrant": "app.database.backends.postgres.vectorstore.QdrantVectorstore",
    "sqlite_vec": "app.database.backends.sqlite.vectorstore.SqliteVecVectorstore",
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
    Thread-safe via double-check locking.
    """
    global _db_instance
    if _db_instance is None:
        with _singleton_lock:
            if _db_instance is None:
                db_type = settings.DATABASE_TYPE
                if db_type not in _DB_BACKENDS:
                    raise ValueError(
                        f"Unsupported DATABASE_TYPE: {db_type}. "
                        f"Supported: {list(_DB_BACKENDS.keys())}"
                    )
                cls = _import_class(_DB_BACKENDS[db_type])
                _db_instance = cls()
                logger.info("Created database instance: %s", db_type)
    assert _db_instance is not None
    return _db_instance


def _get_embed_fn():
    """
    Create a lazy-resolve embedding function using ModelManager.

    The returned function resolves the current embedding model on every call,
    so it works even if the model is configured after vectorstore creation.
    Raises ValueError at call time if no embedding model is configured.
    """

    async def embed_fn(text: str) -> list[float]:
        import litellm
        from app.core.model_manager import ModelManager

        model_id, api_key = await ModelManager.get_embedding_model_instance()
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


def get_vectorstore() -> VectorstoreInterface:
    """
    Get the vectorstore instance (singleton).

    Creates the instance on first call based on VECTORSTORE_TYPE setting.
    If VECTORSTORE_TYPE is not set, defaults based on DATABASE_TYPE.
    Thread-safe via double-check locking.

    On first creation, attempts to inject an embedding function from
    ModelManager so that text-based search() works automatically.
    """
    global _vs_instance
    if _vs_instance is None:
        with _singleton_lock:
            if _vs_instance is None:
                vs_type = settings.VECTORSTORE_TYPE
                if vs_type not in _VS_BACKENDS:
                    raise ValueError(
                        f"Unsupported VECTORSTORE_TYPE: {vs_type}. "
                        f"Supported: {list(_VS_BACKENDS.keys())}"
                    )
                cls = _import_class(_VS_BACKENDS[vs_type])
                instance = cls()
                instance.set_embed_fn(_get_embed_fn())
                _vs_instance = instance
                logger.info(
                    "Created vectorstore instance: %s with embedding function", vs_type
                )
    assert _vs_instance is not None
    return _vs_instance


def get_checkpointer() -> CheckpointInterface:
    """
    Get the checkpointer instance (singleton).

    Creates the instance on first call based on DATABASE_TYPE setting.
    Thread-safe via double-check locking.
    """
    global _cp_instance
    if _cp_instance is None:
        with _singleton_lock:
            if _cp_instance is None:
                db_type = settings.DATABASE_TYPE
                if db_type not in _CP_BACKENDS:
                    raise ValueError(
                        f"No checkpointer backend for DATABASE_TYPE: {db_type}. "
                        f"Supported: {list(_CP_BACKENDS.keys())}"
                    )
                cls = _import_class(_CP_BACKENDS[db_type])
                _cp_instance = cls()
                logger.info("Created checkpointer instance: %s", db_type)
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
    """Initialize the database engine and connection pool.

    Note: Table creation must be done separately by running scripts/init_database.py
    or by calling db.create_tables() explicitly.
    """
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
    """Dispose all backend components. Called during app shutdown.

    Dispose order matters: vectorstore and checkpointer may depend on database,
    so database is disposed last.

    Thread-safe: uses _singleton_lock to protect global variable access.
    The actual dispose() calls are made outside the lock to avoid holding
    it during potentially long operations and because threading.Lock
    does not support await.
    """
    global _db_instance, _vs_instance, _cp_instance

    # Acquire lock to safely read and clear global references
    with _singleton_lock:
        vs = _vs_instance
        cp = _cp_instance
        db = _db_instance
        _vs_instance = None
        _cp_instance = None
        _db_instance = None

    # Dispose outside the lock (order preserved)
    if vs is not None:
        await vs.dispose()
        logger.info("Vectorstore disposed")

    if cp is not None:
        await cp.dispose()
        logger.info("Checkpointer disposed")

    if db is not None:
        await db.dispose()
        logger.info("Database disposed")
