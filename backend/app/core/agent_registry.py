"""Global sub-agent registry — decorator-based registration.

Architecture: LangChain official Single Dispatch Tool pattern.
    Supervisor holds only 2 tools: list_agents + task
    All subagents register via ``@registry.register()`` decorator.
    Adding a new subagent never touches supervisor code or prompt.

Usage::

    from app.core.agent_registry import registry

    @registry.register("my_agent", description="Does X")
    def get_my_agent() -> CompiledStateGraph:
        ...
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

class AgentRegistry:
    """Global registry for sub-agents — decorator-only registration.

    Attributes:
        _agents: {agent_name: factory_callable}
        _descriptions: {agent_name: human-readable description}
    """

    def __init__(self) -> None:
        self._agents: dict[str, SubAgentFactory] = {}
        self._descriptions: dict[str, str] = {}

    # ── Registration API ─────────────────────────────────────────────────

    def register(self, name: str, *, description: str):
        """Decorator: register a subagent factory.

        Args:
            name: Unique agent name (e.g. "chatbot", "rag").
            description: Human-readable capability description used by
                ``list_agents()`` to tell the supervisor what this agent does.

        Usage::

            @registry.register("my_agent", description="Handles X tasks")
            def get_my_agent() -> CompiledStateGraph:
                ...
        """

        def decorator(fn: SubAgentFactory) -> SubAgentFactory:
            self._agents[name] = fn
            self._descriptions[name] = description
            logger.info("SubAgent registered: %s", name)
            return fn

        return decorator

    # ── Query API ────────────────────────────────────────────────────────

    def get(self, name: str) -> SubAgentFactory | None:
        """Get a registered subagent factory by name.

        Returns:
            The factory callable, or ``None`` if not registered.
        """
        return self._agents.get(name)

    def list(self, query: str = "") -> dict[str, str]:
        """List registered subagents with descriptions, optionally filtered.

        Args:
            query: Optional keyword filter (case-insensitive, matches name or description).

        Returns:
            ``{agent_name: description}`` dict.
        """
        if query:
            q = query.lower()
            return {
                k: v
                for k, v in self._descriptions.items()
                if q in k.lower() or q in v.lower()
            }
        return dict(self._descriptions)

    def names(self) -> list[str]:
        """Return all registered agent names in sorted order."""
        return sorted(self._agents.keys())

    # ── Supervisor Tools ─────────────────────────────────────────────────

    def build_list_agents_tool(self):
        """Build the ``list_agents`` discovery tool bound to this registry.

        The supervisor calls this FIRST to discover available specialists.
        """
        registry = self

        @tool
        def list_agents(query: str = "") -> str:
            """Discover available specialist agents. Returns name + description.

            Call this FIRST when you need to find out which specialists are
            available to handle a user request.

            Args:
                query: Optional filter — only return agents matching this keyword.
            """
            agents = registry.list(query)
            if not agents:
                return "No matching specialist agents found."

            lines = [f"- **{name}**: {desc}" for name, desc in sorted(agents.items())]
            return "Available specialist agents:\n" + "\n".join(lines)

        return list_agents

    def build_task_tool(self):
        """Build the ``task`` dispatch tool bound to this registry.

        The supervisor calls this AFTER ``list_agents()`` to delegate work
        to a chosen specialist.
        """
        registry = self

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
            factory = registry.get(agent_name)
            if factory is None:
                available = ", ".join(registry.names())
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

        return task


# ── Global singleton ─────────────────────────────────────────────────────────
# All modules share this single registry instance.

registry = AgentRegistry()

# Pre-built tools for the supervisor (bound to the global registry).
list_agents = registry.build_list_agents_tool()
task = registry.build_task_tool()