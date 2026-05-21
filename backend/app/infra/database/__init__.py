"""
Database infrastructure package.

Public API (stable):
    - get_database / get_vectorstore / get_checkpointer / get_store / get_saver
    - init_database / init_vectorstore / init_checkpointer / init_store / init_all
    - dispose_all
    - Base (SQLAlchemy declarative base for ORM models)

Backends live in ``postgres/`` (prod mode) and ``sqlite/`` (dev mode). Business code
should never import them directly — always go through this package's API.

Both backends expose identical public interfaces (``.session()`` async context manager,
``.engine`` property, ``.initialize()`` / ``.dispose()`` lifecycle), making business
(CRUD) and FastAPI dependency-injection layers completely backend-agnostic.
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

__all__ = [
    "Base",
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
