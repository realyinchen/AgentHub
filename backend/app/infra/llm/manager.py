"""ModelManager — model cache and provider configuration.

This module provides the ModelManager class that manages:
    - Model/provider configuration cached from database
    - Default model IDs per type (llm / vlm)

Public API:
    - get_model_manager(): Get the ModelManager singleton
    - manager.refresh(): Refresh cache after model/provider CRUD operations
    - manager.get_model_info_list(): Get cached models for API responses
    - manager.get_api_key(provider): Get decrypted API key for a provider
    - manager.get_base_url(provider): Get base URL for a provider

Architecture:
    ┌─────────────────────────────────────────────────────────────────────┐
    │                      Model Manager                                   │
    │                                                                      │
    │  Cache (from DB):                                                    │
    │    ├── _models_cache: model_id → Model                              │
    │    ├── _providers_cache: provider → Provider                        │
    │    └── _default_llm_id / _default_vlm_id                            │
    └─────────────────────────────────────────────────────────────────────┘
"""

import asyncio
import logging
from functools import lru_cache
from typing import TYPE_CHECKING, Optional

import litellm

from app.crud import model as model_crud
from app.crud import provider as provider_crud
from app.crud import provider_connection as connection_crud
from app.infra.database import get_database
from app.utils.crypto import decrypt_api_key

if TYPE_CHECKING:
    from app.schemas.model import ModelInfo

logger = logging.getLogger(__name__)

# Enable JSON schema validation for litellm
litellm.enable_json_schema_validation = True


# ─────────────────────────────────────────────────────────────────────────────
# ModelManager
# ─────────────────────────────────────────────────────────────────────────────


class ModelManager:
    """Dynamic model manager backed by the database.

    Caches:
        - all active model configs (`_models_cache: model_id → Model`)
        - all providers with API keys (`_providers_cache: provider → Provider`)
        - default model IDs per type (llm / vlm)

    Hot-reload: call `await manager.refresh()` after any model/provider CRUD
    operation. Thread-safety: an ``asyncio.Lock`` guards cache updates.

    No per-request LLM caching: dynamic model selection requires a fresh
    instance each time. Use ``factory.get_llm()`` for per-request instances.
    """

    def __init__(self) -> None:
        self._models_cache: dict = {}
        self._providers_cache: dict = {}
        self._connections_cache: dict = {}
        self._default_llm_id: Optional[str] = None
        self._default_vlm_id: Optional[str] = None
        self._default_embedding_id: Optional[str] = None
        self._initialized: bool = False
        self._cache_lock: asyncio.Lock | None = None

    @property
    def cache_lock(self) -> asyncio.Lock:
        """Lazily create the asyncio.Lock in the running event loop."""
        if self._cache_lock is None:
            self._cache_lock = asyncio.Lock()
        return self._cache_lock

    # ── Cache refresh ──────────────────────────────────────────────────

    async def refresh(self) -> None:
        """Reload model/provider configuration from the database. Idempotent."""
        logger.info("Refreshing model configuration from database...")

        db = get_database()
        async with db.session() as session:
            providers = await provider_crud.get_all_providers(session)
            connections = await connection_crud.get_connections(session)
            models = await model_crud.get_models_with_provider_config(session)

        # Build new caches
        new_providers = {p.provider: p for p in providers}
        new_connections = {str(c.id): c for c in connections}
        new_models: dict[str, object] = {}
        for m in models:
            model_uuid = str(m.id)
            provider_model_id = str(m.model_id)
            provider_key = str(m.provider)
            new_models[model_uuid] = m
            new_models.setdefault(provider_model_id, m)
            new_models.setdefault(f"{provider_key}/{provider_model_id}", m)

        new_default_llm: Optional[str] = None
        new_default_vlm: Optional[str] = None
        new_default_embedding: Optional[str] = None
        for m in models:
            if not getattr(m, "is_default", False):
                continue
            mt = getattr(m, "model_type", "llm")
            if mt == "llm":
                new_default_llm = str(m.id)
            elif mt == "vlm":
                new_default_vlm = str(m.id)
            elif mt == "embedding":
                new_default_embedding = str(m.id)

        # Atomic swap under lock
        async with self.cache_lock:
            self._providers_cache = new_providers
            self._connections_cache = new_connections
            self._models_cache = new_models
            self._default_llm_id = new_default_llm
            self._default_vlm_id = new_default_vlm
            self._default_embedding_id = new_default_embedding
            self._initialized = True

    # ── Provider accessors ─────────────────────────────────────────────

    def get_provider(self, provider: str):
        """Get provider config from cache."""
        return self._providers_cache.get(provider)

    def get_api_key(self, provider: str) -> Optional[str]:
        """Get decrypted API key for a provider."""
        provider_config = self._providers_cache.get(provider)
        if provider_config and provider_config.api_key:
            return decrypt_api_key(provider_config.api_key)
        return None

    def get_base_url(self, provider: str) -> Optional[str]:
        """Get base URL for a provider (if configured)."""
        provider_config = self._providers_cache.get(provider)
        if provider_config and provider_config.base_url:
            return provider_config.base_url
        return None

    def get_connection(self, connection_id: str | None):
        """Get provider connection config from cache."""
        if not connection_id:
            return None
        return self._connections_cache.get(str(connection_id))

    def get_connection_api_key(self, connection_id: str | None) -> Optional[str]:
        connection = self.get_connection(connection_id)
        if connection and connection.api_key:
            return decrypt_api_key(connection.api_key)
        return None

    def get_connection_base_url(self, connection_id: str | None) -> Optional[str]:
        connection = self.get_connection(connection_id)
        if connection and connection.base_url:
            return connection.base_url
        return None

    # ── Model accessors ───────────────────────────────────────────────

    def get_model(self, model_id: str):
        return self._models_cache.get(model_id)

    def is_thinking_mode_configured(self, model_id: str | None = None) -> bool:
        """Return the configured request mode, not an observed capability."""
        if model_id is None:
            model_id = self._default_llm_id
            if model_id is None:
                return False
        m = self._models_cache.get(model_id)
        return bool(m.thinking) if m else False

    def is_thinking_mode_available(self, model_id: str | None = None) -> bool:
        """Compatibility alias for the legacy endpoint response shape.

        Capability consumers must read append-only probe records instead.
        """
        return self.is_thinking_mode_configured(model_id)

    def get_model_info_list(self, active_only: bool = False) -> "list[ModelInfo]":
        """Return all cached models as ``ModelInfo`` schemas."""
        from app.schemas.model import ModelInfo

        result: list[ModelInfo] = []
        seen: set[str] = set()
        for m in self._models_cache.values():
            model_uuid = str(getattr(m, "id", ""))
            if model_uuid in seen:
                continue
            seen.add(model_uuid)
            if active_only and not getattr(m, "is_active", False):
                continue
            try:
                result.append(ModelInfo.model_validate(m))
            except Exception:
                logger.warning(
                    "Model cache entry failed ModelInfo validation, skipping"
                )
        return result

    @property
    def default_llm_id(self) -> Optional[str]:
        return self._default_llm_id

    @property
    def default_vlm_id(self) -> Optional[str]:
        return self._default_vlm_id

    @property
    def default_embedding_id(self) -> Optional[str]:
        return self._default_embedding_id

    def is_model_active(self, model_id: str) -> bool:
        """Check if a model is present in the cache and marked active."""
        m = self._models_cache.get(model_id)
        return bool(m) and bool(getattr(m, "is_active", False))

    def get_first_active_llm_id(self) -> Optional[str]:
        """Return the first active LLM model_id from cache, or None."""
        seen: set[str] = set()
        for m in self._models_cache.values():
            model_uuid = str(getattr(m, "id", ""))
            if model_uuid in seen:
                continue
            seen.add(model_uuid)
            if getattr(m, "model_type", "llm") == "llm" and getattr(
                m, "is_active", False
            ):
                return str(m.id)
        return None

    def get_first_active_embedding_id(self) -> Optional[str]:
        """Return the first active embedding model UUID from cache."""
        seen: set[str] = set()
        for m in self._models_cache.values():
            model_uuid = str(getattr(m, "id", ""))
            if model_uuid in seen:
                continue
            seen.add(model_uuid)
            if getattr(m, "model_type", "llm") == "embedding" and getattr(
                m, "is_active", False
            ):
                return model_uuid
        return None

    def get_models_count(self) -> int:
        return len({str(getattr(m, "id", "")) for m in self._models_cache.values()})


@lru_cache(maxsize=1)
def get_model_manager() -> ModelManager:
    """Return the application-scoped singleton ``ModelManager`` instance."""
    return ModelManager()
