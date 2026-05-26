"""Shared runtime context types for all agents.

Using @dataclass (instead of TypedDict) follows the LangChain v1 official
pattern — attribute access (ctx.user_id) works naturally in middleware
without dict fallback checks.

Architecture
------------
``AgentRuntimeContext`` is the base class containing fields that **every**
agent needs (user_id, request_id, model_name, etc.).  When a specific agent
requires extra fields, create a subclass::

    from app.agents.types import AgentRuntimeContext

    @dataclass
    class RAGContext(AgentRuntimeContext):
        collection_id: str = ""
        top_k: int = 5

Then pass it via ``AgentSpec(context_schema=RAGContext)``.  Middleware that
only reads base-class fields (dynamic_model, dynamic_prompt) is unaffected.
"""

from dataclasses import dataclass


@dataclass
class AgentRuntimeContext:
    """Base runtime context injected into agent middleware via create_agent().

    Every field has a safe default so the context is always valid even
    when the caller doesn't provide all fields.

    Attributes:
        user_id: User identifier for long-term memory and multi-tenancy.
        request_id: Request identifier for end-to-end tracing.
        model_name: Override model for this request (e.g. "dashscope/qwen3.5-27b").
        thinking_mode: Enable thinking/reasoning mode for the model.
        timezone: IANA timezone for time-context substitution in prompts.
    """

    user_id: str = ""
    request_id: str = ""
    model_name: str = ""
    thinking_mode: bool = False
    timezone: str = "Asia/Shanghai"
