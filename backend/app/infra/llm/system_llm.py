"""System-level LLM — .env-backed singleton for auxiliary tasks.

This module provides a system-level default LLM instance configured via
environment variables. It is used for:
    - Summarization
    - Title generation
    - Compile-time default

Configuration:
    - SYSTEM_DEFAULT_LLM_MODEL: Model identifier (e.g., "openai/gpt-4")
    - SYSTEM_DEFAULT_LLM_API_KEY: API key for the model

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
    """
    global _system_llm_instance

    if _system_llm_instance is not None:
        logger.warning("System LLM already initialized, returning existing instance")
        return _system_llm_instance

    settings = get_settings()
    # validate_system_default_llm guarantees these are present and valid
    assert settings.SYSTEM_DEFAULT_LLM_MODEL is not None
    assert settings.SYSTEM_DEFAULT_LLM_API_KEY is not None

    _system_llm_instance = ChatLiteLLM(
        model=settings.SYSTEM_DEFAULT_LLM_MODEL,
        api_key=settings.SYSTEM_DEFAULT_LLM_API_KEY.get_secret_value(),
        temperature=0,
    )

    logger.info(
        "System default LLM initialized: model=%s",
        settings.SYSTEM_DEFAULT_LLM_MODEL,
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
