"""Supervisor Agent — the single entry point for all user requests.

Built once at startup, cached as module-level singleton. Multi-turn
conversation state is maintained by the checkpointer on the supervisor
graph. Sub-agents are stateless one-shot calls via ``list_agents``/``task`` tools.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import cast

from langchain.agents import create_agent
from langchain.agents.middleware import SummarizationMiddleware, ToolRetryMiddleware
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph.state import CompiledStateGraph
from langgraph.store.base import BaseStore

from app.agents.context import AgentRuntimeContext
from app.agents.middleware.model import dynamic_model
from app.agents.middleware.prompt import make_dynamic_prompt
from app.agents.schemas.routing import RoutingDecision
from app.agents.subagents.registry import list_agents, task  # noqa: F401 — triggers registration
from app.infra.config import get_settings
from app.infra.llm import get_system_default_llm

logger = logging.getLogger(__name__)

_PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"

# CompiledStateGraph is a complex generic from LangGraph. Using the bare
# (unparameterised) type is the recommended pattern — type-checkers treat
# it as an opaque external type, and the actual type params are internal
# LangGraph implementation details that consumers should not depend on.
_supervisor: CompiledStateGraph | None = None


async def build_supervisor(
    checkpointer: BaseCheckpointSaver,
    store: BaseStore | None = None,
) -> CompiledStateGraph:
    """Build and cache the supervisor agent (called once during lifespan startup)."""
    global _supervisor
    model = get_system_default_llm()
    system_prompt = (_PROMPTS_DIR / "supervisor.md").read_text(encoding="utf-8")

    settings = get_settings()

    # Build middleware list dynamically — ToolRetryMiddleware is optional
    # and gated by the TOOL_RETRY_ENABLED feature flag per the Stage 0
    # roadmap (T01).  Only the `task` tool is retried because:
    #   - `task` makes network calls to subagent graphs → benefits from retry
    #   - `list_agents` is a pure in-memory dict lookup → never needs retry
    # Per LangChain official docs: "Scope ToolRetryMiddleware to specific
    # tools rather than retrying everything."
    middleware: list = [
        make_dynamic_prompt("supervisor", store=store),
        dynamic_model,
    ]

    if settings.TOOL_RETRY_ENABLED:
        middleware.append(
            ToolRetryMiddleware(
                max_retries=settings.TOOL_RETRY_MAX_RETRIES,
                backoff_factor=settings.TOOL_RETRY_BACKOFF_FACTOR,
                initial_delay=settings.TOOL_RETRY_INITIAL_DELAY,
                max_delay=settings.TOOL_RETRY_MAX_DELAY,
                tools=["task"],
                retry_on=(ConnectionError, TimeoutError),
                on_failure="continue",
            )
        )

    middleware.append(
        SummarizationMiddleware(
            model=model,
            trigger=("tokens", 4000),
            keep=("messages", 20),
        ),
    )

    # Stage 0 T03: Structured Output routing constraint
    # When USE_STRUCTURED_OUTPUT is True, the supervisor produces a validated
    # RoutingDecision captured in state["structured_response"] instead of
    # free-form natural language.  Defaults to False (existing behavior).
    response_format = RoutingDecision if settings.USE_STRUCTURED_OUTPUT else None

    _supervisor = cast(
        CompiledStateGraph,
        create_agent(
            model=model,
            tools=[list_agents, task],
            system_prompt=system_prompt,
            middleware=middleware,  # pyright: ignore[reportArgumentType]
            checkpointer=checkpointer,
            store=store,
            context_schema=AgentRuntimeContext,
            response_format=response_format,  # pyright: ignore[reportArgumentType]
        ),
    )
    logger.info("Supervisor agent built and ready")
    return _supervisor


def get_supervisor() -> CompiledStateGraph:
    """Return the cached supervisor graph.

    Raises:
        RuntimeError: If ``build_supervisor()`` hasn't been called yet.
    """
    if _supervisor is None:
        raise RuntimeError(
            "Supervisor not built — call build_supervisor() during lifespan startup"
        )
    return _supervisor