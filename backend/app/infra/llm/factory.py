"""LLM instance factory — used by dynamic model middleware.

Provides:
    - get_llm(): Build a ChatLiteLLMRouter via the pre-built Router (recommended).

The primary entry point for runtime model switching (via ``@wrap_model_call``
middleware) is ``get_llm()``, which creates a per-request instance through the
LiteLLM Router (with built-in fallback + retry). No per-request caching is
needed — the Router itself is cached in ``ModelManager``.

For thinking-mode availability queries, use
``ModelManager.is_thinking_mode_available()`` directly.

For the system-level always-available LLM (compile-time default model,
summarization, title generation, etc.), use ``get_system_default_llm()``
from ``app.infra.llm.system``.
"""

from __future__ import annotations

import logging

from langchain_core.language_models import LanguageModelInput
from langchain_core.messages import AIMessage
from langchain_core.runnables import Runnable
from langchain_litellm import ChatLiteLLMRouter

from app.infra.llm.extra_body import build_extra_body
from app.infra.llm.model_manager import ModelManager

logger = logging.getLogger(__name__)


def get_llm(
    model_id: str,
    thinking_mode: bool = False,
    temperature: float = 0,
) -> Runnable[LanguageModelInput, AIMessage]:
    """Build a ChatLiteLLMRouter for the given model.

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
    model_config = ModelManager.get_model(model_id)
    if model_config is None:
        raise ValueError(
            f"Model '{model_id}' not found in database. "
            "Available models: %s" % ", ".join(ModelManager._models_cache.keys())
        )

    router = ModelManager.get_router_sync()
    if router is None:
        raise ValueError("No LiteLLM Router available. Ensure models are configured.")

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
