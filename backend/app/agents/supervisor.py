"""Supervisor Agent — the single entry point for all user requests.

Built once at startup, cached as module-level singleton. Multi-turn
conversation state is maintained by the checkpointer on the supervisor
graph. Sub-agents are stateless one-shot calls via ``list_agents``/``task`` tools.
"""

import logging
from typing import cast

from langchain.agents import create_agent
from langchain.agents.middleware import (
    ModelRetryMiddleware,
    SummarizationMiddleware,
    ToolRetryMiddleware,
)
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


# CompiledStateGraph is a complex generic from LangGraph. Using the bare
# (unparameterised) type is the recommended pattern — type-checkers treat
# it as an opaque external type, and the actual type params are internal
# LangGraph implementation details that consumers should not depend on.
_supervisor: CompiledStateGraph | None = None


async def init_supervisor(
    checkpointer: BaseCheckpointSaver,
    store: BaseStore | None = None,
) -> CompiledStateGraph:
    """Build and cache the supervisor agent (called once during lifespan startup)."""
    global _supervisor
    model = get_system_default_llm()

    # Build middleware list dynamically following the official LangChain
    # middleware order: Pre-processing → Model Selection → Model Retry →
    # Tool Retry → Post-processing.
    #
    # Only the `task` tool is retried because:
    #   - `task` makes network calls to subagent graphs → benefits from retry
    #   - `list_agents` is a pure in-memory dict lookup → never needs retry
    # Per LangChain official docs: "Scope ToolRetryMiddleware to specific
    # tools rather than retrying everything."
    #
    # ModelRetryMiddleware supplements LiteLLM Router's built-in
    # fallback+retry — they operate at different layers.  Router handles
    # provider-level failover; ModelRetryMiddleware handles per-call
    # transient errors with exponential backoff.
    settings = get_settings()

    middleware: list = [
        make_dynamic_prompt("supervisor", store=store),
        dynamic_model,
    ]

    if settings.MODEL_RETRY_ENABLED:
        middleware.append(
            ModelRetryMiddleware(
                max_retries=settings.MODEL_RETRY_MAX_RETRIES,
                backoff_factor=settings.MODEL_RETRY_BACKOFF_FACTOR,
                initial_delay=settings.MODEL_RETRY_INITIAL_DELAY,
                max_delay=settings.MODEL_RETRY_MAX_DELAY,
                jitter=True,
                retry_on=(ConnectionError, TimeoutError),
                on_failure="continue",
            )
        )

    middleware.extend(
        [
            ToolRetryMiddleware(
                tools=["task"],
                retry_on=(ConnectionError, TimeoutError),
                on_failure="continue",
            ),
            SummarizationMiddleware(
                model=model,
                trigger=("tokens", 4000),
                keep=("messages", 20),
            ),
        ]
    )

    _supervisor = cast(
        CompiledStateGraph,
        create_agent(
            model=model,
            tools=[list_agents, task],
            system_prompt="",
            middleware=middleware,
            checkpointer=checkpointer,
            store=store,
            context_schema=AgentRuntimeContext,
            # Structured Output routing constraint the supervisor produces a validated
            # RoutingDecision captured in state["structured_response"] instead of
            # free-form natural language.  Defaults to False (existing behavior).
            response_format=RoutingDecision,
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
