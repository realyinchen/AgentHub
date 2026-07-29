"""LLM infrastructure package.

Public API:
    Lifecycle:
        - init_models(): Initialize all models (call during lifespan startup)

    System LLM (from .env):
        - get_system_llm(): Get system-level default LLM singleton
                           Used for: summarization, title generation, compile-time default

    Runtime LLM:
        - get_llm(model_id, thinking_mode): Get a ChatLiteLLM for runtime use
                                           Models configured in DB (providers + models tables)

    Embedding (database-first, environment fallback):
        - get_embeddings(): Return the startup-activated client.
        - get_persistent_embeddings(): Return it after the provider's real
          output dimension has been observed.

    Model Manager:
        - get_model_manager(): Get the ModelManager singleton for cache access
        - Use manager.refresh() to refresh cache after CRUD operations

Configuration sources:
    - System LLM:     .env (SYSTEM_DEFAULT_LLM_MODEL)
    - Embedding:      DB model/connection, then .env fallback
    - Runtime models: DB (providers + models tables) — /api/v1/models CRUD

Model info for frontend:
    - GET /api/v1/models — Returns all models with: is_active, is_default, thinking, etc.
    - No need to call infra.llm functions directly for model info.

Note: Internal implementation classes (LiteLLMEmbeddings, ModelManager) and
helper functions (_resolve_model_id, _get_default_llm_id, etc.) are not exposed.
Business code should only use the getter functions above.
"""

import logging

from app.infra.llm.embedding import get_embeddings, get_persistent_embeddings
from app.infra.llm.embedding_config import (
    ResolvedEmbeddingConfig,
    build_explicit_embedding_config,
    resolve_embedding_config,
)
from app.infra.llm.factory import get_llm
from app.infra.llm.manager import get_model_manager
from app.infra.llm.resolver import resolve_model_name
from app.infra.llm.system_llm import get_system_llm

logger = logging.getLogger(__name__)

__all__ = [
    "get_system_llm",
    "get_llm",
    "get_embeddings",
    "get_persistent_embeddings",
    "get_model_manager",
    "ResolvedEmbeddingConfig",
    "build_explicit_embedding_config",
    "resolve_embedding_config",
    "resolve_model_name",
]
