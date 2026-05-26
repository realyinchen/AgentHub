"""Chatbot agent module.

Provides the chatbot agent factory and runtime context primitives.
The factory is auto-registered via register_factory() at import time.

Context types
-------------
- ``AgentRuntimeContext`` — shared base for all agents (re-exported here
  for convenience; canonical location is ``app.agents.types``).
- ``ChatbotContext`` — chatbot-specific subclass with ``file`` field.
  Other agents should follow the same pattern (inherit, add fields).
"""

from app.agents.chatbot.chatbot import _create_chatbot_agent
from app.agents.types import AgentRuntimeContext  # re-exported for convenience
from app.agents.chatbot.types import ChatbotContext

__all__ = ["_create_chatbot_agent", "AgentRuntimeContext", "ChatbotContext"]
