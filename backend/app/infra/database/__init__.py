"""
Database infrastructure package — PostgreSQL + pgvector only.

Public API (stable):
    - get_database / get_vectorstore / get_checkpointer / get_store / get_saver
    - init_database / init_vectorstore / init_checkpointer / init_store / init_all
    - dispose_all
    - Base (SQLAlchemy declarative base for ORM models)

Protocol types (for type hints and testing):
    - DatabaseInterface, VectorstoreInterface, CheckpointerInterface, StoreInterface

All backends live in ``postgres/``. Business code should never import them
directly — always go through this package's API.
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
    init_checkpointer,
    init_database,
    init_store,
    init_vectorstore,
)
from app.infra.database.protocols import (
    CheckpointerInterface,
    DatabaseInterface,
    StoreInterface,
    VectorstoreInterface,
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
    "init_database",
    "init_vectorstore",
    "init_checkpointer",
    "init_store",
    "init_all",
    "dispose_all",
    # Protocol types
    "DatabaseInterface",
    "VectorstoreInterface",
    "CheckpointerInterface",
    "StoreInterface",
]
