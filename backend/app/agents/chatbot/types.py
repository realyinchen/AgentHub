"""Shared type definitions for agents.

Extracted to avoid circular imports between chatbot.py and memory/tools.py.
"""

from dataclasses import dataclass


@dataclass
class ChatbotContext:
    """Runtime context for the chatbot agent.

    Using @dataclass (instead of TypedDict) follows the LangChain v1
    official pattern — attribute access (ctx.user_id) works naturally
    in middleware without dict fallback checks.

    Attributes:
        user_id: User identifier for long-term memory lookup
        request_id: Request identifier for end-to-end tracing
        model_name: Override model for this request (e.g. "openai:gpt-4o")
        thinking_mode: Enable thinking/reasoning mode for the model
        timezone: IANA timezone for time-context substitution in prompts
    """

    user_id: str = ""
    request_id: str = ""
    model_name: str = ""
    thinking_mode: bool = False
    timezone: str = "Asia/Shanghai"
