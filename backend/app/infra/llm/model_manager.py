"""ModelManager — model cache, router orchestration, and LLM instance access.

Caches:
    - all active model configs (`_models_cache: model_id → Model`)
    - all providers with API keys (`_providers_cache: provider → Provider`)
    - default model IDs per type (llm / vlm / embedding)
    - one LiteLLM Router (with fallback list) built from the model cache

Hot-reload: call `await refresh()` after any model/provider CRUD operation.
Thread-safety: an `asyncio.Lock` guards Router rebuilds.

Fallback / retry is handled by the LiteLLM Router's built-in `fallbacks`
and `num_retries` — no custom middleware needed.

Runtime model switching is handled by `app.middleware.model.dynamic`
(via `@wrap_model_call` reading `context.model_name`), which calls
`app.infra.llm.factory.get_llm()` to obtain a per-request LLM instance.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Optional

import litellm
from litellm.router import Router

from app.crud import model as model_crud
from app.crud import provider as provider_crud
from app.infra.database import get_database
from app.utils.crypto import decrypt_api_key

logger = logging.getLogger(__name__)

# Enable JSON schema validation for litellm
litellm.enable_json_schema_validation = True


class ModelManager:
    """Dynamic model manager backed by the database.

    Caches:
        - all active model configs (`_models_cache: model_id → Model`)
        - all providers with API keys (`_providers_cache: provider → Provider`)
        - default model IDs per type (llm / vlm / embedding)
        - one LiteLLM Router (with fallback list) built from the model cache

    Hot-reload: call `await refresh()` after any model/provider CRUD operation.
    Thread-safety: an `asyncio.Lock` guards Router rebuilds.

    No per-request LLM caching: dynamic model selection requires a fresh
    instance each time. Use `factory.get_llm()` for per-request instances.
    """

    _models_cache: dict = {}
    _providers_cache: dict = {}
    _default_llm_id: Optional[str] = None
    _default_vlm_id: Optional[str] = None
    _default_embedding_id: Optional[str] = None
    _initialized: bool = False

    _router: Optional[Router] = None
    _router_lock: asyncio.Lock = asyncio.Lock()
    _router_ready: bool = False

    # ── Router lifecycle ───────────────────────────────────────────────

    @classmethod
    async def get_router(cls) -> Optional[Router]:
        """Get (or build) the LiteLLM Router. Returns None if no models exist."""
        if not cls._initialized:
            await cls.refresh()

        if cls._router_ready and cls._router is not None:
            return cls._router

        async with cls._router_lock:
            if cls._router_ready and cls._router is not None:
                return cls._router

            if not cls._models_cache:
                logger.warning("No models in cache, cannot create LiteLLM Router")
                cls._router = None
                cls._router_ready = True
                return None

            model_list = cls._build_model_list()
            fallbacks = cls._build_fallbacks()

            if model_list:
                cls._router = Router(
                    model_list=model_list,
                    fallbacks=fallbacks if fallbacks else [],
                    num_retries=2,
                    retry_after=1,
                )
                logger.info(
                    "LiteLLM Router initialized with %d models, %d fallback rules",
                    len(model_list),
                    len(fallbacks),
                )
            else:
                cls._router = None
                logger.warning("No models configured for LiteLLM Router")

            cls._router_ready = True
            return cls._router

    @classmethod
    def get_router_sync(cls) -> Optional[Router]:
        """Synchronously get the pre-built Router (lifespan must have called refresh()).

        Unlike `get_router()`, this does NOT trigger async refresh — it assumes
        `ModelManager.refresh()` was already called during app startup (see `main.py`).
        Returns None if no models exist or Router hasn't been built yet.
        """
        if cls._router_ready and cls._router is not None:
            return cls._router
        # Fall through to async path — but this is a sync method, so log a warning.
        # Callers should ensure refresh() was called first.
        logger.warning(
            "get_router_sync() called but Router not ready. "
            "Ensure ModelManager.refresh() was called during startup."
        )
        return cls._router

    @classmethod
    def _build_model_list(cls) -> list[dict]:
        """Build LiteLLM Router model_list from cached models/providers.

        NOTE: `extra_body` is deliberately NOT included in `litellm_params`.
        Thinking-mode control is handled entirely by `factory.get_llm()` at
        the per-request layer (via `ChatLiteLLMRouter(..., extra_body=...)`).
        If we baked `extra_body` into the Router's `litellm_params`, fallback
        models would always use the hardcoded default (thinking=False),
        ignoring the per-request `extra_body` passed at call time.
        """
        result = []
        for m in cls._models_cache.values():
            provider_config = cls._providers_cache.get(m.provider)
            decrypted_api_key = ""
            base_url = None
            if provider_config and provider_config.api_key:
                decrypted_api_key = decrypt_api_key(provider_config.api_key)
            if provider_config and provider_config.base_url:
                base_url = provider_config.base_url
            litellm_params = {
                "model": m.model_id,
                "api_key": decrypted_api_key,
            }
            if base_url:
                litellm_params["api_base"] = base_url
            result.append({"model_name": m.model_id, "litellm_params": litellm_params})
        return result

    @classmethod
    def _build_fallbacks(cls) -> list[dict]:
        """Build Router fallback rules sorted by priority (descending).

        Higher priority models only fall back to lower priority models
        (never reverse). This ensures premium → mid-tier → budget flow.
        Within the same priority level, models are sorted alphabetically.
        """
        models = list(cls._models_cache.values())
        if len(models) < 2:
            return []

        # Sort: priority DESC, then model_id ASC (deterministic tiebreak)
        sorted_models = sorted(
            models, key=lambda m: (-getattr(m, "priority", 0), m.model_id)
        )

        by_type: dict[str, list[str]] = {}
        for m in sorted_models:
            if m.is_active:
                by_type.setdefault(m.model_type, []).append(m.model_id)

        fallbacks: list[dict] = []
        for model_ids in by_type.values():
            if len(model_ids) > 1:
                for i, mid in enumerate(model_ids):
                    others = model_ids[i + 1 :]  # only lower priority
                    if others:
                        fallbacks.append({mid: others})
        return fallbacks

    # ── Cache refresh ──────────────────────────────────────────────────

    @classmethod
    async def refresh(cls) -> None:
        """Reload model/provider configuration from the database. Idempotent.

        Thread-safety strategy:
        1. DB queries run outside any lock (I/O should never block readers).
        2. New values are built into local dicts (no mutation of class state).
        3. Under `_router_lock`, all caches + defaults are atomically swapped
           via reference assignment. CPython makes single ref assignments
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
        new_default_embedding: Optional[str] = None
        for m in models:
            if not getattr(m, "is_default", False):
                continue
            mt = getattr(m, "model_type", "llm")
            if mt == "llm":
                new_default_llm = str(m.model_id)
            elif mt == "vlm":
                new_default_vlm = str(m.model_id)
            elif mt == "embedding":
                new_default_embedding = str(m.model_id)

        # Atomic swap under lock — readers see either old or new, never partial
        async with cls._router_lock:
            cls._providers_cache = new_providers
            cls._models_cache = new_models
            cls._default_llm_id = new_default_llm
            cls._default_vlm_id = new_default_vlm
            cls._default_embedding_id = new_default_embedding
            cls._initialized = True

            # Invalidate Router so it gets rebuilt from new caches
            cls._router = None
            cls._router_ready = False

        # Pre-build the Router after refresh so sync accessors work.
        await cls.get_router()

    # ── Read-only cache accessors ──────────────────────────────────────

    @classmethod
    def get_model(cls, model_id: str):
        return cls._models_cache.get(model_id)

    @classmethod
    def is_thinking_mode_available(cls, model_id: str) -> bool:
        m = cls._models_cache.get(model_id)
        return bool(m.thinking) if m else False

    @classmethod
    def get_model_info_list(cls) -> list[dict]:
        return [
            {
                "model_id": m.model_id,
                "model_type": m.model_type,
                "provider": m.provider,
                "thinking": m.thinking,
                "priority": getattr(m, "priority", 0),
                "is_default": m.is_default,
                "is_active": m.is_active,
            }
            for m in cls._models_cache.values()
        ]

    @classmethod
    def get_default_llm_id(cls) -> Optional[str]:
        return cls._default_llm_id

    @classmethod
    def get_default_vlm_id(cls) -> Optional[str]:
        return cls._default_vlm_id

    @classmethod
    def get_default_embedding_id(cls) -> Optional[str]:
        return cls._default_embedding_id

    @classmethod
    async def get_embedding_model(cls, model_id: Optional[str] = None):
        """Return (litellm_model_id, api_key) for use with litellm.aembedding().

        Resolves the embedding model from the cache (or the configured default)
        and returns the LiteLLM-compatible model ID string and decrypted API key.

        Args:
            model_id: Optional model identifier. If None, uses the default
                      embedding model from settings/cache.

        Returns:
            (model_id, api_key) tuple — model_id is the LiteLLM-compatible
            string, api_key is the credential for the provider.
        """
        if not cls._initialized:
            await cls.refresh()

        target_id = model_id or cls._default_embedding_id
        if target_id is None:
            return None, None

        model_config = cls._models_cache.get(target_id)
        if model_config is None:
            logger.warning("Embedding model '%s' not found in cache", target_id)
            return None, None

        provider = model_config.provider
        provider_config = cls._providers_cache.get(provider)
        api_key = ""
        if provider_config and provider_config.api_key:
            api_key = decrypt_api_key(provider_config.api_key)

        # Build the LiteLLM-compatible model ID
        litellm_model_id = cls._resolve_embedding_model_id(
            target_id,
            provider,
            getattr(provider_config, "base_url", None) if provider_config else None,
        )

        return litellm_model_id, api_key

    @staticmethod
    def _resolve_embedding_model_id(
        model_id: str, provider: str, base_url: Optional[str] = None
    ) -> str:
        """Resolve the LiteLLM-compatible embedding model ID.

        LiteLLM expects 'openai/text-embedding-3-small' or 'ollama/nomic-embed-text'.
        We prefix the provider if it's a known provider and the model_id doesn't
        already contain a '/'.
        """
        if "/" in model_id:
            return model_id

        # Ollama and vLLM must be prefixed with the provider name for LiteLLM
        if provider in ("ollama", "vllm"):
            return f"{provider}/{model_id}"

        return model_id

    @classmethod
    def get_models_count(cls) -> int:
        return len(cls._models_cache)


def get_model_manager() -> type[ModelManager]:
    """DI accessor for ModelManager (all methods are classmethods)."""
    return ModelManager
