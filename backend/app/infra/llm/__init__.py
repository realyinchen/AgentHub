"""LLM infrastructure package.

Consolidates all LLM management into clearly separated sub-modules:
    - extra_body.py:       provider/thinking-mode extra_body builder
    - model_manager.py:    ModelManager (cache, router, config access)
    - factory.py:          get_llm() + get_chat_litellm() + is_thinking_mode_available()

All public symbols are re-exported here for backward compatibility.
Import paths like `from app.infra.llm import ModelManager` remain unchanged.
"""

from app.infra.llm.extra_body import build_extra_body
from app.infra.llm.factory import get_chat_litellm, get_llm, is_thinking_mode_available
from app.infra.llm.model_manager import ModelManager, get_model_manager

__all__ = [
    "build_extra_body",
    "ModelManager",
    "get_model_manager",
    "get_llm",
    "get_chat_litellm",
    "is_thinking_mode_available",
]
