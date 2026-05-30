"""Chatbot sub-agent — time query, web search, and conversational Q&A.

This sub-agent is compiled WITHOUT checkpointer (stateless one-shot),
following the official LangChain Subagents pattern. It self-registers
into the SubAgent Registry so the supervisor can discover it via
list_agents() / task() tools.

Uses ``create_subagent()`` from ``_base.py`` — the shared factory that
eliminates boilerplate duplication across all sub-agents.
"""

from __future__ import annotations

import logging
from pathlib import Path

from langgraph.graph.state import CompiledStateGraph

from app.agents.subagents._base import create_subagent, lazy_subagent_cache
from app.core.agent_registry import registry
from app.infra.tools.time import get_current_time
from app.infra.tools.web import create_web_search

logger = logging.getLogger(__name__)


def _build_tools() -> list:
    """Build the tools list for the chatbot sub-agent.

    Graceful degradation: if web search is unavailable (e.g. missing API key),
    falls back to time-only tools.
    """
    tools: list = [get_current_time]
    try:
        tools.append(create_web_search())
    except Exception as exc:
        logger.warning(
            "Web search unavailable (%s), chatbot sub-agent uses time-only tools",
            exc,
        )
    return tools


def _build_chatbot() -> CompiledStateGraph:
    """Build the chatbot sub-agent using the shared factory."""
    prompts_dir = Path(__file__).resolve().parent.parent.parent / "prompts"
    fallback_prompt = (prompts_dir / "chatbot.md").read_text(encoding="utf-8")
    return create_subagent(
        "chatbot",
        tools=_build_tools(),
        system_prompt=fallback_prompt,
    )


_get_chatbot = lazy_subagent_cache(_build_chatbot)


@registry.register(
    "chatbot",
    description=(
        "General-purpose chatbot for everyday Q&A, time queries, "
        "web search, and conversational assistance."
    ),
)
def get_chatbot_subagent() -> CompiledStateGraph:
    """Return the compiled chatbot sub-agent (lazy-init, cached)."""
    return _get_chatbot()