"""Infrastructure layer — centralized resource access for AgentHub.

This package provides the single entry point for infrastructure resources:
- Configuration (Settings)
- Database connections (PostgreSQL, Vectorstore, Checkpointer, Store)

Note: LLM/Embedding resources are available via `app.infra.llm` submodule
to avoid circular imports. Business code should import:

    from app.infra import get_settings, init_database, get_database, ...
    from app.infra.llm import get_system_llm, get_llm, get_embeddings, ...

Public API:
    # Configuration
    get_settings(): Return Pydantic Settings singleton

    # Errors
    AgentHubError: Base exception for all domain errors

    # Database Lifecycle
    init_database(): Initialize all database components (call during startup)
    dispose_database(): Dispose all database components (call during shutdown)

    # Database Resources
    get_database(): Return PostgresDatabase singleton
    get_vectorstore(): Return PGVectorVectorstore singleton
    get_checkpointer(): Return PostgresCheckpointer singleton
    get_store(): Return PostgresStore singleton (or None)
    get_saver(): Return LangGraph-compatible checkpoint saver
    Base: SQLAlchemy declarative base for ORM models
"""

# Configuration
from app.infra.config import get_settings

# Errors
from app.infra.errors import AgentHubError

# Database
from app.infra.database import (
    init_database,
    dispose_database,
    get_database,
    get_vectorstore,
    get_checkpointer,
    get_store,
    get_saver,
    Base,
)

__all__ = [
    # Configuration
    "get_settings",
    # Errors
    "AgentHubError",
    # Database Lifecycle
    "init_database",
    "dispose_database",
    # Database Resources
    "get_database",
    "get_vectorstore",
    "get_checkpointer",
    "get_store",
    "get_saver",
    "Base",
]
