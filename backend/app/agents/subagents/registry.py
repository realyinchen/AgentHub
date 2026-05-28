"""SubAgent Registry — progressive disclosure via single dispatch tool.

Architecture (LangChain official Single Dispatch Tool pattern):
    Supervisor holds only 2 tools: list_agents + task
    All subagents register here. Adding a new subagent never touches
    supervisor code or prompt — just register it below.

Usage::

    from app.agents.subagents.registry import register

    register(
        name="chatbot",
        description="General-purpose chatbot for Q&A, time, web search.",
        factory=get_chatbot_subagent,
    )
"""

from __future__ import annotations

import logging
from typing import Protocol

from langchain.tools import tool
from langgraph.graph.state import CompiledStateGraph
from langgraph.prebuilt import ToolRuntime

logger = logging.getLogger(__name__)


# ── SubAgent interface ───────────────────────────────────────────────────────

class SubAgentFactory(Protocol):
    """Callable that returns a compiled subagent (lazy singleton)."""

    def __call__(self) -> CompiledStateGraph: ...


# ── Registry ─────────────────────────────────────────────────────────────────

_registry: dict[str, SubAgentFactory] = {}
"""All registered subagents. Key = agent_name, Value = lazy factory."""

_descriptions: dict[str, str] = {}
"""Human-readable capability descriptions for list_agents()."""


def register(name: str, description: str, factory: SubAgentFactory) -> None:
    """Register a subagent in the global registry.

    Called at module import time by each subagent module. The description
    is used by list_agents() to tell the supervisor what each agent does.

    Args:
        name: Unique agent name (e.g. "chatbot", "rag", "code").
        description: Human-readable capability description.
        factory: Zero-arg callable that returns CompiledStateGraph.
    """
    _registry[name] = factory
    _descriptions[name] = description
    logger.info("SubAgent registered: %s", name)


# ── Tools exposed to Supervisor ──────────────────────────────────────────────

@tool
def list_agents(query: str = "") -> str:
    """Discover available specialist agents. Returns name + description.

    Call this FIRST when you need to find out which specialists are
    available to handle a user request.

    Args:
        query: Optional filter — only return agents matching this keyword.
    """
    if query:
        filtered = {
            k: v for k, v in _descriptions.items()
            if query.lower() in k.lower() or query.lower() in v.lower()
        }
    else:
        filtered = _descriptions

    if not filtered:
        return "No matching specialist agents found."

    lines = [f"- **{name}**: {desc}" for name, desc in sorted(filtered.items())]
    return "Available specialist agents:\n" + "\n".join(lines)


@tool
async def task(
    agent_name: str,
    description: str,
    runtime: ToolRuntime | None = None,
) -> str:
    """Delegate a task to a specialist subagent.

    Use list_agents() FIRST to discover available agents and their
    capabilities, then call this tool with the chosen agent_name.

    Args:
        agent_name: Name of the specialist agent (from list_agents).
        description: Natural language description of the task to perform.
    """
    factory = _registry.get(agent_name)
    if factory is None:
        available = ", ".join(sorted(_registry.keys()))
        return (
            f"Unknown agent '{agent_name}'. "
            f"Available agents: {available}. "
            f"Use list_agents() to discover capabilities."
        )

    try:
        agent = factory()

        # Pass supervisor's runtime context to the sub-agent so its
        # dynamic_model and dynamic_prompt middleware can read user
        # preferences (model_name, timezone, user_id, etc.).
        invoke_context = None
        if runtime is not None:
            invoke_context = runtime.context

        result = await agent.ainvoke(
            {"messages": [{"role": "user", "content": description}]},
            context=invoke_context,
        )
        messages = result.get("messages", [])
        if not messages:
            return f"[{agent_name}] produced no output."
        last = messages[-1]
        if hasattr(last, "content"):
            return str(last.content)
        return str(last)
    except Exception as exc:
        logger.error("Subagent %s failed: %s", agent_name, exc)
        return f"Agent '{agent_name}' error: {exc}"
