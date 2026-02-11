from contextlib import AbstractAsyncContextManager
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from .db_manager import adb_manager, db_manager
from .checkpointer import get_postgres_saver
from .qdrant_manager import qdrant_manager


def get_checkpointer() -> AbstractAsyncContextManager[AsyncPostgresSaver]:
    """
    Initialize the postgres database checkpointer based on configuration.
    Returns an initialized AsyncCheckpointer instance.
    """
    return get_postgres_saver()


__all__ = [
    "adb_manager",
    "db_manager",
    "get_checkpointer",
    "qdrant_manager",
]
