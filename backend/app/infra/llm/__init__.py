"""LLM infrastructure package.

Consolidates all LLM management into clearly separated sub-modules:
    - extra_body.py:       provider/thinking-mode extra_body builder (internal)
    - model_manager.py:    ModelManager (cache, router, config access)
    - factory.py:          get_llm() + get_chat_litellm()
    - system.py:           get_system_default_llm() — .env-driven singleton

Public API:
    - ModelManager:           model cache, router, thinking-mode queries
    - get_model_manager:      DI accessor for ModelManager
    - get_llm:                create ChatLiteLLMRouter (per-request, with fallback)
    - get_chat_litellm:       create direct ChatLiteLLM (for special cases)
    - get_system_default_llm: system-level always-available LLM (from .env),
                              used by agents at compile time and all internal
                              LLM calls (summarization, memory, titles, ...)

Internal (not exported):
    - build_extra_body:   only used by factory.py / system.py
"""

from app.infra.llm.factory import get_chat_litellm, get_llm
from app.infra.llm.model_manager import ModelManager, get_model_manager
from app.infra.llm.system import get_system_default_llm

__all__ = [
    "ModelManager",
    "get_model_manager",
    "get_llm",
    "get_chat_litellm",
    "get_system_default_llm",
]
