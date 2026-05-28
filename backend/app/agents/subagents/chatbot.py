"""Chatbot sub-agent — time query, web search, and conversational Q&A.

This sub-agent is compiled WITHOUT checkpointer (stateless one-shot),
following the official LangChain Subagents pattern. It self-registers
into the SubAgent Registry so the supervisor can discover it via
list_agents() / task() tools.

Architecture (LangChain v1):
    - Model: compile-time fallback via ``get_system_default_llm()``, with
      ``dynamic_model`` middleware overriding per-request based on
      ``context.model_name`` (same middleware as supervisor).
    - Prompt: compile-time fallback from raw MD file, with
      ``make_dynamic_prompt("chatbot")`` middleware rendering time context
      variables per-request via ``PromptService``.
    - Context: ``context_schema=AgentRuntimeContext`` receives runtime
      context from the supervisor via ``task()`` tool's ``.ainvoke(context=...)``.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import cast

from langchain.agents import create_agent
from langgraph.graph.state import CompiledStateGraph

from app.agents.context import AgentRuntimeContext
from app.agents.middleware.model import dynamic_model
from app.agents.middleware.prompt import make_dynamic_prompt
from app.agents.subagents.registry import register
from app.infra.llm import get_system_default_llm
from app.infra.tools.time import get_current_time
from app.infra.tools.web import create_web_search

logger = logging.getLogger(__name__)

_chatbot_agent: CompiledStateGraph | None = None


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


def get_chatbot_subagent() -> CompiledStateGraph:
    """Return the compiled chatbot sub-agent (lazy-init, cached).

    The agent is compiled ONCE with:
    - A static fallback model (get_system_default_llm)
    - A static fallback system_prompt (raw MD content)
    - Middleware that overrides both at request time:
      - ``make_dynamic_prompt("chatbot")``: renders time context per-request
      - ``dynamic_model``: swaps model based on ``context.model_name``
    - ``context_schema=AgentRuntimeContext``: receives runtime context from supervisor
    """
    global _chatbot_agent
    if _chatbot_agent is not None:
        return _chatbot_agent

    prompts_dir = Path(__file__).resolve().parent.parent.parent / "prompts"
    fallback_prompt = (prompts_dir / "chatbot.md").read_text(encoding="utf-8")

    _chatbot_agent = cast(
        CompiledStateGraph,
        create_agent(
            model=get_system_default_llm(),
            tools=_build_tools(),
            system_prompt=fallback_prompt,
            middleware=[  # pyright: ignore[reportArgumentType]
                make_dynamic_prompt("chatbot"),
                dynamic_model,
            ],
            context_schema=AgentRuntimeContext,
        ),
    )
    logger.info("Chatbot sub-agent compiled (tools=%d)", len(_build_tools()))
    return _chatbot_agent


# ── Self-register into the SubAgent Registry ─────────────────────────────────

register(
    name="chatbot",
    description=(
        "General-purpose chatbot for everyday Q&A, time queries, "
        "web search, and conversational assistance."
    ),
    factory=get_chatbot_subagent,
)