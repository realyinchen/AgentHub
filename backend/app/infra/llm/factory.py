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

    llm = get_llm("qwen3-235b-a22b")  # thinking disabled (default)
    llm = get_llm("qwen3-235b-a22b", thinking_mode=True)  # thinking enabled
"""

import logging

from langchain_core.language_models import LanguageModelInput
from langchain_core.messages import AIMessage
from langchain_core.runnables import Runnable
from langchain_litellm import ChatLiteLLM

from app.infra.config import get_settings
from app.infra.llm.manager import get_model_manager

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# DB-backed LLM factory
# ─────────────────────────────────────────────────────────────────────────────


def get_llm(
    model_id: str,
    thinking_mode: bool = False,
) -> Runnable[LanguageModelInput, AIMessage]:
    """Build a ChatLiteLLM for the given model (DB-backed).

    Creates a fresh ChatLiteLLM instance using API key and base_url from
    ModelManager cache. No fallback support — each call creates a fresh
    instance suitable for per-request use inside ``@wrap_model_call`` middleware.

    Args:
        model_id: Model identifier (e.g. "qwen3-235b-a22b").
                  Can be plain model_id or "provider/model-id" format.
        thinking_mode: Whether to enable thinking/reasoning mode.
                      Defaults to False (disabled).

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

    # Get provider config for API key and base_url
    provider_config = manager.get_provider(model_config.provider)
    if provider_config is None:
        raise ValueError(f"Provider '{model_config.provider}' not found in database.")

    configured_model_id = str(model_config.model_id)
    if configured_model_id.startswith(f"{model_config.provider}/"):
        provider_model_id = configured_model_id.split("/", 1)[1]
    elif configured_model_id.startswith("openai/"):
        provider_model_id = configured_model_id.split("/", 1)[1]
    else:
        provider_model_id = configured_model_id

    is_openai_compatible = bool(
        getattr(provider_config, "is_openai_compatible", False)
    )

    # Get API key (decrypted). Local OpenAI-compatible servers often accept
    # any non-empty key, and some ignore it completely.
    api_key = manager.get_api_key(model_config.provider)
    requires_real_api_key = model_config.provider in {"openrouter"}
    if not api_key and is_openai_compatible and not requires_real_api_key:
        api_key = "local"
    if not api_key:
        raise ValueError(
            f"No API key available for provider '{model_config.provider}'."
        )

    # Get base_url (optional)
    base_url = manager.get_base_url(model_config.provider)

    # LiteLLM routes generic OpenAI-compatible services through the openai/*
    # provider while api_base points at the local server.
    if is_openai_compatible:
        full_model_id = f"openai/{provider_model_id}"
    else:
        full_model_id = f"{model_config.provider}/{provider_model_id}"

    model_kwargs = {"stream_options": {"include_usage": True}}

    # DashScope only: thinking mode is controlled via extra_body. Do not send
    # this provider-specific field to local OpenAI-compatible servers.
    if model_config.provider == "dashscope":
        model_kwargs["extra_body"] = {"enable_thinking": thinking_mode}
    elif model_config.provider == "openrouter" and thinking_mode:
        # OpenRouter exposes reasoning as a top-level OpenAI-compatible
        # parameter. ChatLiteLLM expands model_kwargs into the completion call.
        model_kwargs["reasoning"] = {"enabled": True}
        model_kwargs["include_reasoning"] = True

    logger.info(
        "get_llm: Creating ChatLiteLLM with model=%s, provider=%s, openai_compatible=%s, thinking_mode=%s",
        full_model_id,
        model_config.provider,
        is_openai_compatible,
        thinking_mode,
    )

    # Build litellm_params for ChatLiteLLM
    litellm_params = {
        "model": full_model_id,
        "api_key": api_key,
        "temperature": 0,
        "streaming": True,
        "drop_params": True,
    }

    if base_url:
        litellm_params["api_base"] = base_url

    if model_config.provider == "openrouter":
        settings = get_settings()
        extra_headers: dict[str, str] = {}
        if settings.OPENROUTER_HTTP_REFERER:
            extra_headers["HTTP-Referer"] = settings.OPENROUTER_HTTP_REFERER
        if settings.OPENROUTER_X_TITLE:
            extra_headers["X-Title"] = settings.OPENROUTER_X_TITLE
        if extra_headers:
            litellm_params["extra_headers"] = extra_headers

    llm = ChatLiteLLM(
        **litellm_params,
        model_kwargs=model_kwargs,
    )

    logger.debug(
        "Created ChatLiteLLM: model=%s, thinking_mode=%s",
        model_id,
        thinking_mode,
    )
    return llm
