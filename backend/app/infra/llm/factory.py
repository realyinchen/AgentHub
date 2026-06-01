"""LLM instance factory — unified entry point for all LLM creation.

Provides:
    - get_llm(): Build a ChatLiteLLMRouter via the pre-built Router (DB-backed).
    - get_system_llm(): Build a ChatLiteLLM from .env settings (system-level).

Architecture:
    ┌─────────────────────────────────────────────────────────────────────┐
    │                      LLM Factory                                     │
    │  ┌─────────────────────┐    ┌─────────────────────┐                 │
    │  │ get_llm()           │    │ get_system_llm()    │                 │
    │  │ (DB-backed)         │    │ (.env-backed)       │                 │
    │  │ ChatLiteLLMRouter   │    │ ChatLiteLLM         │                 │
    │  │ + fallback/retry    │    │ (singleton)         │                 │
    │  └─────────────────────┘    └─────────────────────┘                 │
    │           ↓                          ↓                              │
    │  Runtime model switching    System-level always-available LLM        │
    │  (via @wrap_model_call)     (compile-time, summarization, titles)   │
    └─────────────────────────────────────────────────────────────────────┘

The primary entry point for runtime model switching (via ``@wrap_model_call``
middleware) is ``get_llm()``, which creates a per-request instance through the
LiteLLM Router (with built-in fallback + retry). No per-request caching is
needed — the Router itself is cached in ``ModelManager``.

For the system-level always-available LLM (compile-time default model,
summarization, title generation, etc.), use ``get_system_llm()``.
"""

from __future__ import annotations

import logging
from functools import lru_cache
from typing import Any

from langchain_core.language_models import LanguageModelInput
from langchain_core.messages import AIMessage
from langchain_core.runnables import Runnable
from langchain_litellm import ChatLiteLLM, ChatLiteLLMRouter

from app.infra.config import get_settings

logger = logging.getLogger(__name__)


def _get_build_extra_body():
    """Lazy import to avoid circular imports."""
    from app.infra.llm.manager import build_extra_body
    return build_extra_body


def _get_model_manager():
    """Lazy import to avoid circular imports."""
    from app.infra.llm.manager import get_model_manager
    return get_model_manager()


# ─────────────────────────────────────────────────────────────────────────────
# DB-backed LLM (runtime model switching)
# ─────────────────────────────────────────────────────────────────────────────


def get_llm(
    model_id: str,
    thinking_mode: bool = False,
    temperature: float = 0,
) -> Runnable[LanguageModelInput, AIMessage]:
    """Build a ChatLiteLLMRouter for the given model (DB-backed).

    Uses the pre-built LiteLLM Router (cached in ModelManager), so fallback
    and retry are automatically handled. No instance caching — each call
    creates a fresh bound instance suitable for per-request use inside
    ``@wrap_model_call`` middleware.

    Args:
        model_id: Model identifier (e.g. "gpt-4o" or "zhipu/glm-4-flash").
        thinking_mode: Whether to enable thinking/reasoning mode.
        temperature: Model temperature (default 0 for deterministic output).

    Returns:
        A bound ChatLiteLLMRouter ready for invoke/stream.

    Raises:
        ValueError: If the model is not found in the cache or no Router available.
    """
    manager = _get_model_manager()
    model_config = manager.get_model(model_id)
    if model_config is None:
        raise ValueError(f"Model '{model_id}' not found in database. ")

    router = manager.router
    if router is None:
        raise ValueError("No LiteLLM Router available. Ensure models are configured.")

    build_extra_body = _get_build_extra_body()
    extra_body = build_extra_body(model_config.provider, thinking_mode)

    # Pass extra_body as constructor kwarg (NOT via .bind()).
    # .bind() returns a RunnableBinding, which is NOT a BaseChatModel subclass
    # and causes issues with request.override(model=llm) in @wrap_model_call
    # middleware (LangChain v1 dynamic model selection expects BaseChatModel).
    # ChatLiteLLMRouter inherits from ChatLiteLLM, which accepts extra_body
    # as a constructor kwarg — it flows into self._client_params and is
    # forwarded to the LiteLLM Router on every completion call.
    llm = ChatLiteLLMRouter(
        router=router,
        model_name=model_id,
        temperature=temperature,
        streaming=True,
        drop_params=True,
        model_kwargs={"stream_options": {"include_usage": True}},
        extra_body=extra_body,
    )

    logger.info(
        "Created ChatLiteLLMRouter: model=%s, temp=%s, thinking_mode=%s, extra_body_keys=%s",
        model_id,
        temperature,
        thinking_mode,
        list(extra_body.keys()) if extra_body else [],
    )
    return llm


# ─────────────────────────────────────────────────────────────────────────────
# System-level LLM (.env-backed singleton)
# ─────────────────────────────────────────────────────────────────────────────


@lru_cache(maxsize=1)
def get_system_llm() -> ChatLiteLLM:
    """Return the system-level default LLM (cached singleton).

    Built once, on first access, from `.env` settings. Subsequent calls return
    the same instance — this is the always-available system LLM.

    Used by:
        - Agent factories at compile time (default_model parameter)
        - SummarizationMiddleware
        - Long-term memory extraction
        - Conversation title generation
        - Any other internal/implicit LLM call

    Configuration is fail-fast: if SYSTEM_DEFAULT_LLM_MODEL or
    SYSTEM_DEFAULT_LLM_API_KEY are missing, `Settings` raises at application
    startup (see config.py `validate_system_default_llm`), so by the time this
    module is called we are guaranteed both values exist and are valid.

    Returns:
        A ChatLiteLLM instance configured with streaming + drop_params +
        include_usage stream_options + provider-specific extra_body
        (thinking disabled by default).
    """
    settings = get_settings()
    # validate_system_default_llm guarantees these are present and valid
    assert settings.SYSTEM_DEFAULT_LLM_MODEL is not None
    assert settings.SYSTEM_DEFAULT_LLM_API_KEY is not None

    # Parse provider from "provider/model-id" (validator enforces "/" presence)
    provider = settings.SYSTEM_DEFAULT_LLM_MODEL.split("/", 1)[0]

    # Built via **kwargs — `drop_params` and `extra_body` are valid LiteLLM
    # kwargs forwarded to the underlying provider, though Pylance can't
    # statically see them.
    build_extra_body = _get_build_extra_body()
    llm_kwargs: dict[str, Any] = {
        "model": settings.SYSTEM_DEFAULT_LLM_MODEL,
        "api_key": settings.SYSTEM_DEFAULT_LLM_API_KEY.get_secret_value(),
        "temperature": 0,
        "streaming": True,
        "drop_params": True,
        # CRITICAL: include_usage=True enables stable token usage in streaming
        "model_kwargs": {"stream_options": {"include_usage": True}},
        "extra_body": build_extra_body(provider, False),
    }
    llm = ChatLiteLLM(**llm_kwargs)

    logger.info(
        "System default LLM initialized: model=%s, provider=%s",
        settings.SYSTEM_DEFAULT_LLM_MODEL,
        provider,
    )
    return llm


# ─────────────────────────────────────────────────────────────────────────────
# Backward compatibility alias
# ─────────────────────────────────────────────────────────────────────────────

# Keep `get_system_default_llm` as alias for backward compatibility
get_system_default_llm = get_system_llm