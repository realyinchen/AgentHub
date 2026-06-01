"""
Database infrastructure package — PostgreSQL + pgvector only.

Public API (stable):
    - get_database / get_vectorstore / get_checkpointer / get_store / get_saver
    - get_or_create_vectorstore (lazy initialization for multi-table support)
    - init_database / dispose_database
    - Base (SQLAlchemy declarative base for ORM models)
    - TTL helpers: build_ttl_filter, build_expires_at_metadata

Business code should never import backend implementations directly —
always go through this package's API.
"""

from app.infra.database.base import Base
from app.infra.database.factory import (
    dispose_database,
    get_checkpointer,
    get_database,
    get_or_create_vectorstore,
    get_saver,
    get_store,
    get_vectorstore,
    init_database,
)
from app.infra.database.vectorstore import (
    build_ttl_filter,
    build_expires_at_metadata,
)

__all__ = [
    # Core
    "Base",
    # Factory functions
    "get_database",
    "get_vectorstore",
    "get_or_create_vectorstore",
    "get_checkpointer",
    "get_store",
    "get_saver",
    "init_database",
    "dispose_database",
    # TTL helpers
    "build_ttl_filter",
    "build_expires_at_metadata",
]
