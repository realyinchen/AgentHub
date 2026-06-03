"""LLM Factory — creates ChatLiteLLM instances for runtime use.

This module provides factory functions for creating LLM instances that are
backed by the database (providers + models tables). It directly creates
ChatLiteLLM instances using API key and base_url from ModelManager.

Provider: DashScope (Alibaba Cloud) only.
    - Thinking mode controlled via extra_body: {"enable_thinking": bool}
    - Default: thinking mode DISABLED

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

    # Parse provider from model_id (format: "provider/model-id")
    # Support both "provider/model-id" and plain "model-id" formats
    if "/" in model_id:
        short_model_id = model_id.split("/", 1)[1]
    else:
        short_model_id = model_id

    model_config = manager.get_model(short_model_id)
    if model_config is None:
        raise ValueError(f"Model '{model_id}' not found in database.")

    # Get provider config for API key and base_url
    provider_config = manager.get_provider(model_config.provider)
    if provider_config is None:
        raise ValueError(f"Provider '{model_config.provider}' not found in database.")

    # Get API key (decrypted)
    api_key = manager.get_api_key(model_config.provider)
    if not api_key:
        raise ValueError(
            f"No API key available for provider '{model_config.provider}'."
        )

    # Get base_url (optional)
    base_url = manager.get_base_url(model_config.provider)

    # Build full model_id with provider prefix (required by LiteLLM)
    full_model_id = f"{model_config.provider}/{short_model_id}"

    # DashScope only: thinking mode controlled via extra_body (disabled by default)
    # IMPORTANT: extra_body must be passed via model_kwargs, NOT as a direct kwarg.
    # ChatLiteLLM does NOT have an 'extra_body' field defined,
    # so passing extra_body=... directly gets ignored by Pydantic.
    # model_kwargs is merged into _default_params and forwarded to litellm completion.
    extra_body = {"enable_thinking": thinking_mode}

    logger.info(
        "get_llm: Creating ChatLiteLLM with model=%s, thinking_mode=%s, extra_body=%s",
        full_model_id,
        thinking_mode,
        extra_body,
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

    llm = ChatLiteLLM(
        **litellm_params,
        model_kwargs={
            "stream_options": {"include_usage": True},
            "extra_body": extra_body,
        },
    )

    logger.debug(
        "Created ChatLiteLLM: model=%s, thinking_mode=%s",
        model_id,
        thinking_mode,
    )
    return llm
