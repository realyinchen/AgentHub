"""LLM infrastructure package.

Consolidates all LLM management into two clearly separated modules:
    - manager.py:  ModelManager (cache, router, config access) + build_extra_body
    - factory.py:  get_llm() + get_system_llm() — unified LLM factory

Public API:
    - ModelManager:           model cache, router, thinking-mode queries
    - get_model_manager:      DI accessor for ModelManager
    - get_llm:                create ChatLiteLLMRouter (per-request, with fallback)
    - get_system_llm:         system-level always-available LLM (from .env),
                              used by agents at compile time and all internal
                              LLM calls (summarization, memory, titles, ...)

Backward compatibility:
    - get_system_default_llm: alias for get_system_llm (deprecated)
"""

from app.infra.llm.factory import get_llm, get_system_llm, get_system_default_llm
from app.infra.llm.manager import ModelManager, get_model_manager

__all__ = [
    "ModelManager",
    "get_model_manager",
    "get_llm",
    "get_system_llm",
    "get_system_default_llm",  # backward compatibility
]