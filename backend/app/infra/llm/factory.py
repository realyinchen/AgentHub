"""LLM Factory — creates ChatLiteLLMRouter instances for runtime model switching.

This module provides factory functions for creating LLM instances that are
backed by the database (providers + models tables). It uses the pre-built
LiteLLM Router from ModelManager for fallback and retry handling.

Public API:
    - get_llm(model_id, thinking_mode): Get a ChatLiteLLMRouter for runtime use

Usage:
    from app.infra.llm import get_llm

    llm = get_llm("zhipu/glm-4-flash", thinking_mode=True)
    response = await llm.ainvoke("Hello!")
"""

import logging

from langchain_core.language_models import LanguageModelInput
from langchain_core.messages import AIMessage
from langchain_core.runnables import Runnable
from langchain_litellm import ChatLiteLLMRouter

from app.infra.llm.manager import get_model_manager

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Provider-specific extra_body builder for thinking-mode control
# ─────────────────────────────────────────────────────────────────────────────


def _build_extra_body(provider: str, thinking_enabled: bool) -> dict:
    """Build provider-specific `extra_body` for thinking-mode control.

    Each provider has a different mechanism for enabling/disabling
    reasoning/thinking mode.

    IMPORTANT: When `thinking_enabled=False`, we MUST explicitly disable
    reasoning to prevent LiteLLM from auto-enabling it based on model name.

    Supported providers:
        - DashScope (Alibaba Cloud): `enable_thinking: bool`
        - ZhipuAI (zai):             `thinking: {type: enabled|disabled}`
        - Others:                    no params

    Args:
        provider: Provider name (e.g. "dashscope", "zai", "openai").
        thinking_enabled: Whether to enable thinking/reasoning mode.

    Returns:
        Dict to pass as `extra_body` to LiteLLM.
    """
    p = provider.lower()
    if p == "dashscope":
        return {"enable_thinking": thinking_enabled}
    if p == "zai":
        return {"thinking": {"type": "enabled" if thinking_enabled else "disabled"}}
    return {}


# ─────────────────────────────────────────────────────────────────────────────
# DB-backed LLM factory
# ─────────────────────────────────────────────────────────────────────────────


def get_llm(
    model_id: str,
    thinking_mode: bool = False,
) -> Runnable[LanguageModelInput, AIMessage]:
    """Build a ChatLiteLLMRouter for the given model (DB-backed).

    Uses the pre-built LiteLLM Router (cached in ModelManager), so fallback
    and retry are automatically handled. No instance caching — each call
    creates a fresh bound instance suitable for per-request use inside
    ``@wrap_model_call`` middleware.

    Args:
        model_id: Full model identifier (e.g. "zhipu/glm-4-flash").
                  Format: "provider/model-id"
        thinking_mode: Whether to enable thinking/reasoning mode.

    Returns:
        A bound ChatLiteLLMRouter ready for invoke/stream.

    Raises:
        ValueError: If the model is not found in the cache or no Router available.
    """
    manager = get_model_manager()

    # Parse provider from model_id (format: "provider/model-id")
    if "/" in model_id:
        provider = model_id.split("/", 1)[0]
        short_model_id = model_id.split("/", 1)[1]
    else:
        provider = ""
        short_model_id = model_id

    model_config = manager.get_model(short_model_id)
    if model_config is None:
        raise ValueError(f"Model '{model_id}' not found in database.")

    # Build full model_id with provider prefix (required by LiteLLM Router)
    # The Router's model_list uses "provider/model_id" format for model_name
    full_model_id = f"{model_config.provider}/{short_model_id}"

    router = manager.router
    if router is None:
        raise ValueError("No LiteLLM Router available. Ensure models are configured.")

    extra_body = _build_extra_body(provider or model_config.provider, thinking_mode)

    # Pass extra_body as constructor kwarg (NOT via .bind()).
    # .bind() returns a RunnableBinding, which is NOT a BaseChatModel subclass
    # and causes issues with request.override(model=llm) in @wrap_model_call
    # middleware (LangChain v1 dynamic model selection expects BaseChatModel).
    # ChatLiteLLMRouter inherits from ChatLiteLLM, which accepts extra_body
    # as a constructor kwarg — it flows into self._client_params and is
    # forwarded to the LiteLLM Router on every completion call.
    llm = ChatLiteLLMRouter(
        router=router,
        model_name=full_model_id,
        temperature=0,
        streaming=True,
        drop_params=True,
        model_kwargs={"stream_options": {"include_usage": True}},
        extra_body=extra_body,
    )

    logger.debug(
        "Created ChatLiteLLMRouter: model=%s, thinking_mode=%s",
        model_id,
        thinking_mode,
    )
    return llm
