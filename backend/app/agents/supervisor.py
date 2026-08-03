"""Agent — the single entry point for all user requests.

Built once at startup via `init_agent()` during the FastAPI lifespan.
Multi-turn conversation state is maintained by the checkpointer.

Architecture:
    Controller proposal -> WorkflowCompiler -> SystemRuntime -> PlanReceipt
    -> Supervisor

The supervisor consumes receipts and produces language. It has no direct tool
execution path; deterministic and LLM planning both happen before this graph.
"""

import logging
from typing import cast

from langchain.agents import create_agent
from langchain.agents.middleware import SummarizationMiddleware
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph.state import CompiledStateGraph
from langgraph.store.base import BaseStore

from app.agents.context import AgentRuntimeContext
from app.agents.middleware.content_filter import content_filter
from app.agents.middleware.model import dynamic_model
from app.agents.middleware.prompt import supervisor_prompt

logger = logging.getLogger(__name__)

# ── Module-level singleton ──────────────────────────────────────────────────

_agent_instance: CompiledStateGraph | None = None


# ── Public API ──────────────────────────────────────────────────────────────


def is_ready() -> bool:
    """Check if agent is initialized."""
    return _agent_instance is not None


async def init_agent(
    checkpointer: BaseCheckpointSaver,
    store: BaseStore | None = None,
) -> CompiledStateGraph:
    """Build and cache the agent.

    Called once during FastAPI lifespan startup. Idempotent —
    subsequent calls return the already-built instance.
    """
    global _agent_instance

    if _agent_instance is not None:
        logger.warning("Agent already initialized — returning existing instance")
        return _agent_instance

    # Lazy import to avoid circular dependency at module load time.
    from app.infra.llm import get_system_llm

    model = get_system_llm()

    # Capabilities execute only through SystemRuntime before this graph.
    tools: list = []

    # Build middleware list following the official LangChain middleware order:
    # Pre-processing → Model Selection → Content Filter → Post-processing.
    # Note: Fallback/retry is handled by LiteLLM Router, no ModelRetryMiddleware needed.
    middleware: list = [
        supervisor_prompt,  # @dynamic_prompt: loads MD template + time context
        dynamic_model,  # DynamicModelMiddleware: runtime model switching (sync + async)
        content_filter,  # ContentFilterMiddleware: removes non-standard content types
        SummarizationMiddleware(
            model=model,
            trigger=("tokens", 4000),
            keep=("messages", 20),
        ),
    ]

    _agent_instance = cast(
        CompiledStateGraph,
        create_agent(
            model=model,
            tools=tools,
            system_prompt="",  # supervisor_prompt middleware will override
            middleware=middleware,
            checkpointer=checkpointer,
            store=store,
            context_schema=AgentRuntimeContext,
        ),
    )

    logger.info("Receipt-consuming supervisor built with no direct tools")
    return _agent_instance


def get_agent() -> CompiledStateGraph:
    """Return the cached agent graph.

    Raises:
        RuntimeError: If `init_agent()` hasn't been called during lifespan.
    """
    if _agent_instance is None:
        raise RuntimeError(
            "Agent not built — call init_agent() during lifespan startup"
        )
    return _agent_instance
