"""Supervisor runtime context — the single context schema for the supervisor agent.

Merges the former ``app.agents.types.AgentRuntimeContext`` and the ``file`` field
from the former ``ChatbotContext``. All sub-agent invocations use this same
context — no agent-specific subclasses needed because the supervisor graph
is the only compiled agent with checkpointer middleware.
"""

from dataclasses import dataclass
from uuid import UUID


@dataclass
class AgentRuntimeContext:
    """Runtime context injected into the supervisor agent via ``create_agent()``.

    Every field has a safe default so the context is always valid even when
    the caller doesn't provide all fields.

    Attributes:
        user_id: User identifier for long-term memory and multi-tenancy.
        thread_id: Conversation identifier for memory traceability.
        request_id: Request identifier for end-to-end tracing.
        model_name: Override model for this request (e.g. "dashscope/qwen3.5-27b").
        thinking_mode: Enable thinking/reasoning mode for the model.
        timezone: IANA timezone for time-context substitution in prompts.
        file: File path/URL for file-based Q&A scenarios (from custom_data).
        action_plan: The planner decision that authorized runtime actions.
        plan_receipt: SystemRuntime proof and bounded capability outputs.
    """

    user_id: UUID | None = None
    thread_id: UUID | None = None
    request_id: str = ""
    model_name: str = ""
    thinking_mode: bool = False
    timezone: str = "Asia/Shanghai"
    file: str = ""
    action_plan: dict | None = None
    plan_receipt: dict | None = None
