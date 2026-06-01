"""
Database infrastructure package — PostgreSQL + pgvector only.

Public API (stable):
    - get_database / get_vectorstore / get_checkpointer / get_store / get_saver
    - init_all / dispose_all
    - Base (SQLAlchemy declarative base for ORM models)

Business code should never import backend implementations directly —
always go through this package's API.
"""

from app.infra.database.base import Base
from app.infra.database.factory import (
    dispose_all,
    get_checkpointer,
    get_database,
    get_saver,
    get_store,
    get_vectorstore,
    init_all,
)

__all__ = [
    # Core
    "Base",
    # Factory functions
    "get_database",
    "get_vectorstore",
    "get_checkpointer",
    "get_store",
    "get_saver",
    "init_all",
    "dispose_all",
]
