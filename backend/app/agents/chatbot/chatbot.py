"""Chatbot agent with time and web search capabilities."""

import logging
from typing import Any

from app.agents.registry import register_factory
from app.agents.factory import AgentSpec, create_standard_agent
from app.agents.chatbot.types import ChatbotContext
from app.infra.tools.time import get_current_time
from app.infra.tools.web import create_web_search


logger = logging.getLogger(__name__)


# ── Tools ───────────────────────────────────────────────────────────────

_tools_cache: list | None = None
_tools_init_failed: bool = False


def reset_tools_cache() -> None:
    """Reset the tools cache so the next agent compile re-initialises tools.

    Called by ``reload_agents`` / ``reload_agent`` on every compilation
    to ensure transient failures (e.g. Tavily API temporarily down) are
    retried on the next reload rather than cached forever.
    """
    global _tools_cache, _tools_init_failed
    _tools_cache = None
    _tools_init_failed = False


def _get_tools() -> list:
    """Get tools lazily — cached after first successful initialization.

    Graceful degradation:
    - If web search API key is missing, falls back to time tools only
    - Cache is reset on each ``reload_agents()`` call so transient
      failures are retried on the next reload.
    """
    global _tools_cache, _tools_init_failed
    if _tools_cache is not None:
        return _tools_cache

    try:
        web_search = create_web_search()
        _tools_cache = [get_current_time, web_search]
    except (ValueError, KeyError) as e:
        logger.warning(
            "Web search tool initialization failed (%s: %s), falling back to time only",
            type(e).__name__,
            e,
        )
        _tools_cache = [get_current_time]
        _tools_init_failed = True
    return _tools_cache


# ── Agent Factory ────────────────────────────────────────────────────────


def _create_chatbot_agent(checkpointer: Any = None, store: Any = None) -> Any:
    """Create and return a compiled chatbot agent.

    Delegates to create_standard_agent() with an AgentSpec — the
    canonical middleware chain and summarization config are centralized
    in app/agents/factory.py. See AgentSpec and create_standard_agent()
    for full middleware documentation.

    This factory is called by reload_agents() at startup (and on
    DB-triggered refresh) with the current checkpointer. The compiled
    graph is cached in memory and reused for every request — no
    per-request compilation overhead.
    """
    reset_tools_cache()
    return create_standard_agent(
        AgentSpec(
            agent_id="chatbot",
            tools_factory=_get_tools,
            context_schema=ChatbotContext,
        ),
        checkpointer=checkpointer,
        store=store,
    )


# ── Register factory ─────────────────────────────────────────────────────

register_factory("chatbot", _create_chatbot_agent)
logger.info("Agent factory registered: chatbot")
