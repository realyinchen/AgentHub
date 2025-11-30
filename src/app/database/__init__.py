from contextlib import AbstractAsyncContextManager
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from .postgres import get_postgres_saver
from .qdrant import (
    initialize_qdrant_client,
    close_qdrant_client,
    get_qdrant_client,
)


def initialize_database() -> AbstractAsyncContextManager[AsyncPostgresSaver]:
    """
    Initialize the postgres database checkpointer based on configuration.
    Returns an initialized AsyncCheckpointer instance.
    """
    return get_postgres_saver()


__all__ = [
    "initialize_database",
    "initialize_qdrant_client",
    "close_qdrant_client",
    "get_qdrant_client",
]
