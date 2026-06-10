"""System-level LLM — .env-backed singleton for auxiliary tasks.

This module provides a system-level default LLM instance configured via
environment variables. It is used for:
    - Summarization
    - Title generation
    - Compile-time default

Configuration:
    - SYSTEM_DEFAULT_LLM_MODEL: Model identifier (e.g., "dashscope/qwen3.6-27b")
    - SYSTEM_DEFAULT_LLM_API_KEY: API key for the model
    - SYSTEM_DEFAULT_LLM_BASE_URL: Optional OpenAI-compatible API base URL

Usage:
    from app.infra.llm import get_system_llm

    llm = get_system_llm()
    response = await llm.ainvoke("Generate a title for this conversation...")
"""

import logging

from langchain_litellm import ChatLiteLLM

from app.infra.config import get_settings

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# System-level LLM singleton
# ─────────────────────────────────────────────────────────────────────────────

_system_llm_instance: ChatLiteLLM | None = None


def init_system_llm() -> ChatLiteLLM:
    """Internal: Initialize system-level LLM from .env.

    Called by init_models() during startup.
    Used for: summarization, title generation, compile-time default.
    No streaming, no token counting — minimal config for auxiliary tasks.

    IMPORTANT: System LLM must NOT enable thinking mode.
    Thinking mode returns content blocks with reasoning, which breaks
    title generation and other auxiliary tasks that expect plain text.
    DashScope: thinking mode controlled via extra_body={"enable_thinking": False}
    """
    global _system_llm_instance

    if _system_llm_instance is not None:
        logger.warning("System LLM already initialized, returning existing instance")
        return _system_llm_instance

    settings = get_settings()
    # validate_system_default_llm guarantees these are present and valid
    assert settings.SYSTEM_DEFAULT_LLM_MODEL is not None
    assert settings.SYSTEM_DEFAULT_LLM_API_KEY is not None

    provider, model_id = settings.SYSTEM_DEFAULT_LLM_MODEL.split("/", 1)
    openai_compatible_provider = provider in {
        "lmstudio",
        "ollama",
        "openai-compatible",
        "openrouter",
    }
    use_openai_compatible = bool(
        settings.SYSTEM_DEFAULT_LLM_BASE_URL or openai_compatible_provider
    )
    litellm_model = (
        f"openai/{model_id}" if use_openai_compatible else settings.SYSTEM_DEFAULT_LLM_MODEL
    )

    # Build litellm_params for ChatLiteLLM
    litellm_params = {
        "model": litellm_model,
        "api_key": settings.SYSTEM_DEFAULT_LLM_API_KEY.get_secret_value(),
        "temperature": 0,
    }

    if settings.SYSTEM_DEFAULT_LLM_BASE_URL:
        litellm_params["api_base"] = settings.SYSTEM_DEFAULT_LLM_BASE_URL

    if provider == "openrouter":
        extra_headers: dict[str, str] = {}
        if settings.OPENROUTER_HTTP_REFERER:
            extra_headers["HTTP-Referer"] = settings.OPENROUTER_HTTP_REFERER
        if settings.OPENROUTER_X_TITLE:
            extra_headers["X-Title"] = settings.OPENROUTER_X_TITLE
        if extra_headers:
            litellm_params["extra_headers"] = extra_headers

    # DashScope models: explicitly disable thinking mode via extra_body
    # This ensures title generation and other auxiliary tasks get plain text responses
    if settings.SYSTEM_DEFAULT_LLM_MODEL.startswith("dashscope/"):
        litellm_params["model_kwargs"] = {
            "extra_body": {"enable_thinking": False},
        }

    _system_llm_instance = ChatLiteLLM(**litellm_params)

    logger.info(
        "System default LLM initialized: model=%s, litellm_model=%s, thinking_mode=False",
        settings.SYSTEM_DEFAULT_LLM_MODEL,
        litellm_model,
    )
    return _system_llm_instance


def get_system_llm() -> ChatLiteLLM:
    """Return the system-level default LLM instance.

    This LLM is configured via environment variables and is used for
    auxiliary tasks like summarization and title generation.

    Returns:
        ChatLiteLLM: The system-level LLM instance.

    Raises:
        RuntimeError: If init_models() hasn't been called during lifespan.
    """
    if _system_llm_instance is None:
        raise RuntimeError(
            "System LLM not initialized — call init_models() during lifespan startup"
        )
    return _system_llm_instance
