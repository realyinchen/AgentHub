"""
SQLite backends (development / testing).

This package contains all SQLite-based infrastructure backends:
- database      : SQLAlchemy async engine + aiosqlite (relational data)
- vectorstore   : sqlite-vec extension for local vector search (dev mode only)
- checkpointer  : LangGraph AsyncSqliteSaver (short-term memory)
- store         : InMemoryStore (long-term memory - NOT persisted)

For development/test stacks only; production uses postgres/ package.
"""

from app.infra.database.sqlite.database import (
    SQLiteDatabase,
)
from app.infra.database.sqlite.vectorstore import (
    SqliteVecVectorstore,
)
from app.infra.database.sqlite.checkpointer import (
    SqliteCheckpointer,
)
from app.infra.database.sqlite.store import (
    InMemoryStoreBackend,
)

__all__ = [
    "SQLiteDatabase",
    "SqliteVecVectorstore",
    "SqliteCheckpointer",
    "InMemoryStoreBackend",
]
