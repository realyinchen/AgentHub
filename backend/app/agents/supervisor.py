"""Agent — the single entry point for all user requests.

Built once at startup via ``AgentManager.init()`` during the FastAPI
lifespan. Multi-turn conversation state is maintained by the checkpointer.

Architecture (simplified — no subagent delegation):
    User → Agent (checkpointer + dynamic prompt + dynamic model)
                │
                ├── get_current_time  (@tool: time queries)
                └── web_search        (@tool: web search)

Tools are injected directly — no list_agents/task delegation overhead.
"""

from __future__ import annotations

import logging
from typing import cast

from langchain.agents import create_agent
from langchain.agents.middleware import (
    ModelRetryMiddleware,
    SummarizationMiddleware,
)
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph.state import CompiledStateGraph
from langgraph.store.base import BaseStore

from app.agents.context import AgentRuntimeContext
from app.agents.middleware.model import dynamic_model
from app.agents.middleware.prompt import make_dynamic_prompt
from app.infra.config import get_settings
from app.infra.llm import get_system_default_llm
from app.agents.tools import get_current_time, create_web_search

logger = logging.getLogger(__name__)


class AgentManager:
    """Controls the lifecycle of the compiled agent graph.

    Intended as a module-level singleton: one instance per process, one
    ``init()`` call during FastAPI lifespan, and zero-overhead ``get()``
    at request time.

    Usage::

        # In lifespan:
        await agent_manager.init(checkpointer, store)

        # In endpoint handlers:
        agent = agent_manager.get()
    """

    def __init__(self) -> None:
        self._instance: CompiledStateGraph | None = None

    @property
    def is_ready(self) -> bool:
        return self._instance is not None

    async def init(
        self,
        checkpointer: BaseCheckpointSaver,
        store: BaseStore | None = None,
    ) -> CompiledStateGraph:
        """Build and cache the agent.

        Called once during FastAPI lifespan startup. Idempotent —
        subsequent calls return the already-built instance.
        """
        if self._instance is not None:
            logger.warning("Agent already initialized — returning existing instance")
            return self._instance

        model = get_system_default_llm()
        settings = get_settings()

        # Build tools directly (no subagent delegation)
        tools: list = [get_current_time]
        try:
            tools.append(create_web_search())
        except Exception as exc:
            logger.warning(
                "Web search unavailable (%s), agent uses time-only tools",
                exc,
            )

        # Build middleware list following the official LangChain middleware order:
        # Pre-processing → Model Selection → Model Retry → Post-processing.
        middleware: list = [
            make_dynamic_prompt("agent", store=store),  # uses prompts/agent.md
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

        middleware.append(
            SummarizationMiddleware(
                model=model,
                trigger=("tokens", 4000),
                keep=("messages", 20),
            )
        )

        self._instance = cast(
            CompiledStateGraph,
            create_agent(
                model=model,
                tools=tools,  # ← Direct tool injection
                system_prompt="",  # dynamic_prompt middleware will override
                middleware=middleware,
                checkpointer=checkpointer,
                store=store,
                context_schema=AgentRuntimeContext,
            ),
        )
        logger.info("Agent built with %d tools: %s", len(tools), [t.name for t in tools])
        return self._instance

    def get(self) -> CompiledStateGraph:
        """Return the cached agent graph.

        Raises:
            RuntimeError: If ``init()`` hasn't been called during lifespan.
        """
        if self._instance is None:
            raise RuntimeError(
                "Agent not built — call agent_manager.init() during lifespan startup"
            )
        return self._instance


# Module-level singleton — the only instance across the process.
agent_manager = AgentManager()


# ── Convenience aliases for backward compatibility ─────────────────────────
# Kept as module-level functions so existing callers (api/v1/chat/run.py,
# main.py) don't need import path changes.


async def init_supervisor(
    checkpointer: BaseCheckpointSaver,
    store: BaseStore | None = None,
) -> CompiledStateGraph:
    """Build and cache the agent (called once during lifespan startup)."""
    return await agent_manager.init(checkpointer, store)


def get_supervisor() -> CompiledStateGraph:
    """Return the cached agent graph.

    Raises:
        RuntimeError: If ``init_supervisor()`` hasn't been called yet.
    """
    return agent_manager.get()