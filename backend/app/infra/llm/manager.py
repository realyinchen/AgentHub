"""ModelManager — model cache and router orchestration.

This module provides the ModelManager class that manages:
    - Model/provider configuration cached from database
    - LiteLLM Router for runtime model switching with fallback support
    - Default model IDs per type (llm / vlm)

Public API:
    - get_model_manager(): Get the ModelManager singleton
    - manager.refresh(): Refresh cache after model/provider CRUD operations
    - manager.get_model_info_list(): Get cached models for API responses
    - manager.router: Access the LiteLLM Router for factory use

Architecture:
    ┌─────────────────────────────────────────────────────────────────────┐
    │                      Model Manager                                   │
    │                                                                      │
    │  Cache (from DB):                                                    │
    │    ├── _models_cache: model_id → Model                              │
    │    ├── _providers_cache: provider → Provider                        │
    │    └── _default_llm_id / _default_vlm_id                            │
    │                                                                      │
    │  Router (built from cache):                                          │
    │    └── LiteLLM Router with fallback list                             │
    └─────────────────────────────────────────────────────────────────────┘
"""

import asyncio
import logging
from functools import lru_cache
from typing import TYPE_CHECKING, Optional

import litellm
from litellm.router import Router

from app.crud import model as model_crud
from app.crud import provider as provider_crud
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
        - one LiteLLM Router (with fallback list) built from the model cache

    Hot-reload: call `await manager.refresh()` after any model/provider CRUD
    operation. Thread-safety: an ``asyncio.Lock`` (lazily created per-instance
    via ``router_lock`` property) guards Router rebuilds.

    No per-request LLM caching: dynamic model selection requires a fresh
    instance each time. Use ``factory.get_llm()`` for per-request instances.
    """

    def __init__(self) -> None:
        self._models_cache: dict = {}
        self._providers_cache: dict = {}
        self._default_llm_id: Optional[str] = None
        self._default_vlm_id: Optional[str] = None
        self._initialized: bool = False

        self._router: Optional[Router] = None
        self._router_lock: asyncio.Lock | None = (
            None  # lazily created in the running event loop
        )
        self._router_ready: bool = False

    @property
    def router_lock(self) -> asyncio.Lock:
        """Lazily create the asyncio.Lock in the running event loop.

        Creating ``asyncio.Lock()`` at module-import time (or as a class
        variable) risks binding to the wrong event loop.  Deferring creation
        to the first access in the *running* event loop avoids that.
        """
        if self._router_lock is None:
            self._router_lock = asyncio.Lock()
        return self._router_lock

    @property
    def router(self) -> Optional[Router]:
        """Get the pre-built LiteLLM Router (must call refresh() first).

        Returns None if no models exist or Router hasn't been built yet.
        """
        return self._router

    # ── Router lifecycle ───────────────────────────────────────────────

    async def get_router(self) -> Optional[Router]:
        """Get (or build) the LiteLLM Router. Returns None if no models exist."""
        if not self._initialized:
            await self.refresh()

        if self._router_ready and self._router is not None:
            return self._router

        async with self.router_lock:
            if self._router_ready and self._router is not None:
                return self._router

            if not self._models_cache:
                logger.warning("No models in cache, cannot create LiteLLM Router")
                self._router = None
                self._router_ready = True
                return None

            model_list = self._build_model_list()
            fallbacks = self._build_fallbacks()

            if model_list:
                self._router = Router(
                    model_list=model_list,
                    fallbacks=fallbacks if fallbacks else [],
                )
                logger.info(
                    "LiteLLM Router initialized with %d models, %d fallback rules",
                    len(model_list),
                    len(fallbacks),
                )
            else:
                self._router = None
                logger.warning("No models configured for LiteLLM Router")

            self._router_ready = True
            return self._router

    def _build_model_list(self) -> list[dict]:
        """Build LiteLLM Router model_list from cached models/providers.

        NOTE: ``extra_body`` is deliberately NOT included in
        ``litellm_params``.  Thinking-mode control is handled entirely by
        ``factory.get_llm()`` at the per-request layer (via
        ``ChatLiteLLMRouter(..., extra_body=...)``).  If we baked
        ``extra_body`` into the Router's ``litellm_params``, fallback models
        would always use the hardcoded default (thinking=False), ignoring the
        per-request ``extra_body`` passed at call time.
        """
        result = []
        for m in self._models_cache.values():
            provider_config = self._providers_cache.get(m.provider)
            decrypted_api_key = ""
            base_url = None
            if provider_config and provider_config.api_key:
                decrypted_api_key = decrypt_api_key(provider_config.api_key)
            if provider_config and provider_config.base_url:
                base_url = provider_config.base_url
            full_model_id = f"{m.provider}/{m.model_id}"
            litellm_params = {
                "model": full_model_id,
                "api_key": decrypted_api_key,
            }
            if base_url:
                litellm_params["api_base"] = base_url
            result.append(
                {"model_name": full_model_id, "litellm_params": litellm_params}
            )
        return result

    def _build_fallbacks(self) -> list[dict]:
        """Build Router fallback rules.

        Within each model_type, every model falls back to all other models
        of the same type. LiteLLM Router handles intelligent ordering.
        """
        models = list(self._models_cache.values())
        if len(models) < 2:
            return []

        by_type: dict[str, list[str]] = {}
        for m in models:
            if m.is_active:
                full_id = f"{m.provider}/{m.model_id}"
                by_type.setdefault(m.model_type, []).append(full_id)

        fallbacks: list[dict] = []
        for model_ids in by_type.values():
            if len(model_ids) > 1:
                for mid in model_ids:
                    others = [x for x in model_ids if x != mid]
                    fallbacks.append({mid: others})
        return fallbacks

    # ── Cache refresh ──────────────────────────────────────────────────

    async def refresh(self) -> None:
        """Reload model/provider configuration from the database. Idempotent.

        Thread-safety strategy:
        1. DB queries run outside any lock (I/O should never block readers).
        2. New values are built into local dicts (no mutation of instance state).
        3. Under ``router_lock``, all caches + defaults are atomically swapped
           via reference assignment.  CPython makes single ref assignments
           atomic, so lock-free readers see either 100% old or 100% new state.
        4. Router is invalidated under the same lock, then rebuilt outside it
           (get_router() performs its own double-checked locking).
        """
        logger.info("Refreshing model configuration from database...")

        db = get_database()
        async with db.session() as session:
            providers = await provider_crud.get_all_providers(session)
            models = await model_crud.get_models_with_provider_config(session)

        # Build new caches off the critical path (no lock — I/O is done)
        new_providers = {p.provider: p for p in providers}
        new_models = {m.model_id: m for m in models}

        new_default_llm: Optional[str] = None
        new_default_vlm: Optional[str] = None
        for m in models:
            if not getattr(m, "is_default", False):
                continue
            mt = getattr(m, "model_type", "llm")
            if mt == "llm":
                new_default_llm = str(m.model_id)
            elif mt == "vlm":
                new_default_vlm = str(m.model_id)

        # Atomic swap under lock — readers see either old or new, never partial
        async with self.router_lock:
            self._providers_cache = new_providers
            self._models_cache = new_models
            self._default_llm_id = new_default_llm
            self._default_vlm_id = new_default_vlm
            self._initialized = True

            # Invalidate Router so it gets rebuilt from new caches
            self._router = None
            self._router_ready = False

        # Pre-build the Router after refresh so sync accessors work.
        await self.get_router()

    # ── Read-only cache accessors ──────────────────────────────────────

    def get_model(self, model_id: str):
        return self._models_cache.get(model_id)

    def is_thinking_mode_available(self, model_id: str | None = None) -> bool:
        """Check if thinking mode is available for a model.

        If model_id is None, checks the default LLM model.
        """
        if model_id is None:
            model_id = self._default_llm_id
            if model_id is None:
                return False
        m = self._models_cache.get(model_id)
        return bool(m.thinking) if m else False

    def get_model_info_list(self, active_only: bool = False) -> "list[ModelInfo]":
        """Return all cached models as ``ModelInfo`` schemas.

        Args:
            active_only: When ``True``, filter to ``is_active`` models only.
        """
        from app.schemas.model import ModelInfo

        result: list[ModelInfo] = []
        for m in self._models_cache.values():
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

    def is_model_active(self, model_id: str) -> bool:
        """Check if a model is present in the cache and marked active."""
        m = self._models_cache.get(model_id)
        return bool(m) and bool(getattr(m, "is_active", False))

    def get_first_active_llm_id(self) -> Optional[str]:
        """Return the first active LLM model_id from cache, or None."""
        for m in self._models_cache.values():
            if getattr(m, "model_type", "llm") == "llm" and getattr(
                m, "is_active", False
            ):
                return str(m.model_id)
        return None

    def get_models_count(self) -> int:
        return len(self._models_cache)


@lru_cache(maxsize=1)
def get_model_manager() -> ModelManager:
    """Return the application-scoped singleton ``ModelManager`` instance.

    Cached via ``@lru_cache`` — all callers share the same instance.
    """
    return ModelManager()
