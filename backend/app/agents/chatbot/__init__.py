"""Chatbot agent module.

Provides the chatbot agent factory and its runtime context schema.
The factory is auto-registered via register_factory() at import time.
"""

from app.agents.chatbot.chatbot import _create_chatbot_agent
from app.agents.chatbot.types import ChatbotContext

__all__ = ["_create_chatbot_agent", "ChatbotContext"]
