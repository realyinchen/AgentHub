"""System-level default LLM singleton.

Provides a single, always-available ChatLiteLLM instance, configured purely
from .env (SYSTEM_DEFAULT_LLM_MODEL + SYSTEM_DEFAULT_LLM_API_KEY). Used by:
  - Agent factories at compile time (default_model parameter)
  - SummarizationMiddleware
  - Long-term memory extraction (future)
  - Conversation title generation
  - Any other internal/implicit LLM call

This is completely independent of ModelManager / DB — those handle the
user-facing dynamic model switching, not system-level operation.

Configuration is fail-fast: if SYSTEM_DEFAULT_LLM_MODEL or
SYSTEM_DEFAULT_LLM_API_KEY are missing, `Settings` raises at application
startup (see config.py `validate_system_default_llm`), so by the time this
module is called we are guaranteed both values exist and are valid.
"""

from __future__ import annotations

import logging
from functools import lru_cache
from typing import Any

from langchain_litellm import ChatLiteLLM

from app.infra.config import get_settings
from app.infra.llm.extra_body import build_extra_body

logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def get_system_default_llm() -> ChatLiteLLM:
    """Return the system-level default LLM (cached singleton).

    Built once, on first access, from `.env` settings. Subsequent calls return
    the same instance — this is the always-available system LLM.

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
