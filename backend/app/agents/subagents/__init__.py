"""Sub-agent package — one-shot agents wrapped as @tool for the supervisor.

Each sub-agent is compiled with ``create_agent()`` **without** checkpointer
(stateless by design per LangChain official Subagents pattern). They are
invoked by the supervisor via ``.ainvoke()`` on a single-turn message.

Sub-agents self-register via ``@register_subagent`` at import time.
Import them here to trigger registration before the supervisor is built.

Design (LangChain v1):
    - Model: compile-time fallback via ``get_system_default_llm()``, with
      ``dynamic_model`` middleware overriding per-request based on
      ``context.model_name`` (same middleware as supervisor).
    - Prompt: compile-time fallback from raw MD file, with
      ``make_dynamic_prompt(agent_id)`` middleware rendering time context
      variables per-request via ``PromptService``.
    - Context: ``context_schema=AgentRuntimeContext`` receives runtime
      context from the supervisor via ``task()`` tool's ``.ainvoke(context=...)``.

    Sub-agents and the supervisor share the same middleware infrastructure
    (``dynamic_model`` + ``make_dynamic_prompt``), ensuring consistent
    behavior: user-selected models and timezones apply globally.
"""

from app.agents.subagents.chatbot import get_chatbot_subagent  # noqa: F401 — triggers register()

__all__ = [
    "get_chatbot_subagent",
]