"""Base factory for sub-agents — eliminates boilerplate duplication.

Every sub-agent follows the same creation pattern:
    1. Lazy-init with module-level cache
    2. ``create_agent()`` with ``AgentRuntimeContext`` as context_schema
    3. ``dynamic_model`` + ``make_dynamic_prompt(name)`` middleware
    4. ``get_system_default_llm()`` as compile-time fallback model

This module provides ``create_subagent()`` to encapsulate that pattern.
Adding a new sub-agent becomes a 5-line function.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import cast

from langchain.agents import create_agent
from langgraph.graph.state import CompiledStateGraph

from app.agents.context import AgentRuntimeContext
from app.agents.middleware.model import dynamic_model
from app.agents.middleware.prompt import make_dynamic_prompt
from app.infra.llm import get_system_default_llm

logger = logging.getLogger(__name__)


def create_subagent(
    name: str,
    *,
    tools: list,
    system_prompt: str,
    store: object | None = None,
) -> CompiledStateGraph:
    """Build a stateless one-shot sub-agent with shared middleware.

    This is the single canonical way to build sub-agents. Every call shares
    the same middleware stack (dynamic prompt + dynamic model) and context
    schema, ensuring consistent behavior across all specialists.

    Args:
        name: Unique agent name used as the ``make_dynamic_prompt()`` key
            and for log messages.
        tools: LangChain tools available to this sub-agent.
        system_prompt: Static fallback system prompt (raw string). The
            ``make_dynamic_prompt`` middleware overrides this at runtime
            with a rendered prompt from the DB (or this fallback if the DB
            has no override).
        store: Optional ``BaseStore`` for long-term memory (passed through
            to ``create_agent()``).

    Returns:
        A compiled ``CompiledStateGraph`` ready for ``.ainvoke()``.
    """
    agent = cast(
        CompiledStateGraph,
        create_agent(
            model=get_system_default_llm(),
            tools=tools,
            system_prompt=system_prompt,
            middleware=[
                make_dynamic_prompt(name, store=store),
                dynamic_model,
            ],
            context_schema=AgentRuntimeContext,
        ),
    )
    logger.info("Sub-agent '%s' compiled (tools=%d)", name, len(tools))
    return agent


def lazy_subagent_cache(
    build_fn: Callable[[], CompiledStateGraph],
) -> Callable[[], CompiledStateGraph]:
    """Wrap a sub-agent builder with module-level lazy-init caching.

    Usage::

        _get_chatbot = lazy_subagent_cache(_build_chatbot)

    The returned callable builds the agent once and caches it — subsequent
    calls return the cached instance.
    """
    _cached: CompiledStateGraph | None = None

    def _wrapper() -> CompiledStateGraph:
        nonlocal _cached
        if _cached is None:
            _cached = build_fn()
        return _cached

    return _wrapper