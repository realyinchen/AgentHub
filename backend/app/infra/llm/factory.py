"""LLM Factory — creates ChatLiteLLM instances for runtime use.

This module provides factory functions for creating LLM instances that are
backed by the database (providers + models tables). It directly creates
ChatLiteLLM instances using API key and base_url from ModelManager.

Providers:
    - Native LiteLLM providers such as DashScope
    - OpenAI-compatible local providers such as LM Studio and Ollama

Public API:
    - get_llm(model_id, thinking_mode): Get a ChatLiteLLM for runtime use

Usage:
    from app.infra.llm import get_llm

    llm = get_llm("qwen3-235b-a22b")  # use the database configuration
    llm = get_llm("qwen3-235b-a22b", thinking_mode=True)  # thinking enabled
"""

import logging
from collections.abc import Mapping

from langchain_core.language_models import LanguageModelInput
from langchain_core.messages import AIMessage
from langchain_core.runnables import Runnable

from app.infra.config import get_settings
from app.infra.llm.manager import get_model_manager
from app.infra.llm.provider_adapters import get_provider_adapter

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# DB-backed LLM factory
# ─────────────────────────────────────────────────────────────────────────────


def get_llm(
    model_id: str,
    thinking_mode: bool | None = None,
) -> Runnable[LanguageModelInput, AIMessage]:
    """Build a ChatLiteLLM for the given model (DB-backed).

    Creates a fresh ChatLiteLLM instance using API key and base_url from
    ModelManager cache. No fallback support — each call creates a fresh
    instance suitable for per-request use inside ``@wrap_model_call`` middleware.

    Args:
        model_id: Model identifier (e.g. "qwen3-235b-a22b").
                  Can be plain model_id or "provider/model-id" format.
        thinking_mode: Explicit thinking/reasoning override. When omitted,
                      use the selected database model's configured mode.

    Returns:
        A ChatLiteLLM ready for invoke/stream.

    Raises:
        ValueError: If the model is not found in the cache or no API key available.
    """
    manager = get_model_manager()

    # Prefer exact DB model_id matching. Some local model names contain "/",
    # so only fall back to stripping provider prefixes for legacy UI values.
    model_config = manager.get_model(model_id)
    if model_config is None and "/" in model_id:
        model_config = manager.get_model(model_id.split("/", 1)[1])
    if model_config is None:
        raise ValueError(f"Model '{model_id}' not found in database.")
    effective_thinking_mode = (
        bool(getattr(model_config, "thinking", False))
        if thinking_mode is None
        else bool(thinking_mode)
    )

    connection = manager.get_connection(str(model_config.connection_id))
    provider_key = connection.provider if connection is not None else model_config.provider

    # Get provider config for adapter metadata.
    provider_config = manager.get_provider(provider_key)
    if provider_config is None:
        raise ValueError(f"Provider '{provider_key}' not found in database.")

    is_openai_compatible = bool(
        getattr(provider_config, "is_openai_compatible", False)
    )
    api_key = (
        manager.get_connection_api_key(str(model_config.connection_id))
        if model_config.connection_id
        else None
    )
    base_url = (
        manager.get_connection_base_url(str(model_config.connection_id))
        if model_config.connection_id
        else None
    )

    return create_llm_from_config(
        provider=provider_key,
        model_id=str(model_config.model_id),
        api_key=api_key or manager.get_api_key(provider_key),
        base_url=base_url or manager.get_base_url(provider_key),
        is_openai_compatible=is_openai_compatible,
        thinking_mode=effective_thinking_mode,
    )


def create_llm_from_config(
    *,
    provider: str,
    model_id: str,
    api_key: str | None,
    base_url: str | None,
    is_openai_compatible: bool,
    thinking_mode: bool = False,
    extra_headers: Mapping[str, str] | None = None,
) -> Runnable[LanguageModelInput, AIMessage]:
    """Build a ChatLiteLLM from explicit provider/model configuration.

    Runtime calls and validation calls share this function so provider adapter
    behavior stays identical.
    """
    adapter = get_provider_adapter(provider)
    provider_model_id = adapter.normalize_model_id(provider, model_id)

    # Local OpenAI-compatible servers often accept any non-empty key, and some
    # ignore it completely.
    effective_api_key = api_key
    if (
        not effective_api_key
        and is_openai_compatible
        and not adapter.requires_real_api_key
    ):
        effective_api_key = "local"
    if not effective_api_key:
        raise ValueError(f"No API key available for provider '{provider}'.")

    full_model_id = adapter.litellm_model_name(
        provider,
        provider_model_id,
        is_openai_compatible,
    )
    model_kwargs = adapter.model_kwargs(thinking_mode)

    logger.info(
        "get_llm: Creating ChatLiteLLM with model=%s, provider=%s, openai_compatible=%s, thinking_mode=%s",
        full_model_id,
        provider,
        is_openai_compatible,
        thinking_mode,
    )

    # Build litellm_params for ChatLiteLLM
    litellm_params = {
        "model": full_model_id,
        "api_key": effective_api_key,
        "temperature": 0,
        "streaming": adapter.streaming_enabled(thinking_mode),
        "drop_params": True,
    }

    if base_url:
        litellm_params["api_base"] = base_url

    adapter_params = adapter.extra_litellm_params(get_settings())
    merged_headers = dict(adapter_params.get("extra_headers") or {})
    merged_headers.update(dict(extra_headers or {}))
    if merged_headers:
        adapter_params["extra_headers"] = merged_headers
    litellm_params.update(adapter_params)
    chat_model_cls = adapter.chat_model_cls

    llm = chat_model_cls(
        **litellm_params,
        model_kwargs=model_kwargs,
    )

    logger.debug(
        "Created ChatLiteLLM: model=%s, thinking_mode=%s",
        provider_model_id,
        thinking_mode,
    )
    return llm
