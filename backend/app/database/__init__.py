"""
Database Package

Provides factory functions for obtaining database, vectorstore,
and checkpointer instances. Business code should use these factory
functions rather than importing backend classes directly.
"""

from app.database.factory import (
    get_database,
    get_vectorstore,
    get_checkpointer,
    get_saver,
    init_database,
    init_vectorstore,
    init_checkpointer,
    init_all,
    dispose_all,
)

__all__ = [
    "get_database",
    "get_vectorstore",
    "get_checkpointer",
    "get_saver",
    "init_database",
    "init_vectorstore",
    "init_checkpointer",
    "init_all",
    "dispose_all",
]
