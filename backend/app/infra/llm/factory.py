"""LLM instance factories — used by agents and dynamic model middleware.

Provides:
    - get_llm(): Build a ChatLiteLLMRouter via the pre-built Router (recommended).
    - get_chat_litellm(): Build a direct ChatLiteLLM instance (for special cases).

The primary entry point for runtime model switching (via `@wrap_model_call`
middleware) is `get_llm()`, which creates a per-request instance through the
LiteLLM Router (with built-in fallback + retry). No per-request caching is
needed — the Router is already cached in ModelManager.

For LangGraph `bind_tools()` scenarios, `get_chat_litellm()` builds a direct
ChatLiteLLM without the Router layer.

For thinking-mode availability queries, use
`ModelManager.is_thinking_mode_available()` directly.
"""

from __future__ import annotations

import logging
from typing import Any

from langchain_core.language_models import LanguageModelInput
from langchain_core.messages import AIMessage
from langchain_core.runnables import Runnable
from langchain_litellm import ChatLiteLLM
from langchain_litellm import ChatLiteLLMRouter

from app.infra.llm.extra_body import build_extra_body
from app.infra.llm.model_manager import ModelManager
from app.utils.crypto import decrypt_api_key

logger = logging.getLogger(__name__)


def get_llm(
    model_id: str,
    thinking_mode: bool = False,
    temperature: float = 0,
) -> Runnable[LanguageModelInput, AIMessage]:
    """Build a ChatLiteLLMRouter for the given model (recommended).

    Uses the pre-built LiteLLM Router (cached in ModelManager), so fallback
    and retry are automatically handled. No instance caching — each call
    creates a fresh bound instance.

    Args:
        model_id: Model identifier (e.g. "gpt-4o" or "zhipu/glm-4-flash").
        thinking_mode: Whether to enable thinking/reasoning mode.
        temperature: Model temperature (default 0 for deterministic output).

    Returns:
        A bound ChatLiteLLMRunner ready for invoke/stream.

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


def get_chat_litellm(
    model: str,
    temperature: float = 0,
    thinking_mode: bool = False,
    tools: list | None = None,
) -> ChatLiteLLM | Any:
    """Build a ChatLiteLLM instance for LangGraph streaming (special cases).

    This creates a direct ChatLiteLLM instance WITHOUT the Router layer.
    Use this when you need precise model control (e.g. for the default model
    passed to `create_agent()` at agent-creation time).

    Behaviour:
        - LiteLLM model name gets the provider prefix auto-added if missing
        - `drop_params=True` so unsupported params don't raise
        - `stream_options.include_usage=True` so usage_metadata appears in stream chunks
        - `extra_body` is ALWAYS set (explicit on/off for thinking mode)
        - If `tools` are given, `bind_tools()` re-passes extra_body and model_kwargs
          (because `bind_tools()` returns a new Runnable that does NOT inherit them).
    """
    model_config = ModelManager.get_model(model)

    # Ensure provider prefix (LiteLLM expects "provider/model")
    litellm_model = model
    if "/" not in model and model_config:
        litellm_model = f"{model_config.provider.lower()}/{model}"

    llm_kwargs: dict[str, Any] = {
        "model": litellm_model,
        "temperature": temperature,
        "streaming": True,
        "drop_params": True,
        # CRITICAL: include_usage=True enables stable token usage in streaming
        "model_kwargs": {"stream_options": {"include_usage": True}},
    }

    has_api_key = False
    if model_config:
        provider_config = ModelManager._providers_cache.get(model_config.provider)
        if provider_config and provider_config.api_key:
            llm_kwargs["api_key"] = decrypt_api_key(provider_config.api_key)
            has_api_key = True

    extra_body: dict = {}
    if model_config:
        extra_body = build_extra_body(model_config.provider, thinking_mode)
        if extra_body:
            llm_kwargs["extra_body"] = extra_body

    llm = ChatLiteLLM(**llm_kwargs)

    if tools:
        # bind_tools() returns a new Runnable that does NOT inherit constructor
        # kwargs — re-pass extra_body and stream_options explicitly.
        llm = llm.bind_tools(
            tools,
            extra_body=extra_body,
            model_kwargs={"stream_options": {"include_usage": True}},
        )

    logger.info(
        "Created ChatLiteLLM: model=%s, temp=%s, streaming=True, include_usage=True, "
        "thinking_mode=%s, extra_body_keys=%s, tools=%d, api_key=%s",
        litellm_model,
        temperature,
        thinking_mode,
        list(extra_body.keys()) if extra_body else [],
        len(tools) if tools else 0,
        "Yes" if has_api_key else "No",
    )
    return llm


