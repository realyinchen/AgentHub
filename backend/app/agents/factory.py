"""Lightweight, immutable spec-based standard agent factory.

This module exists solely to prevent copy-paste of create_agent()
boilerplate across multiple agents. It does NOT introduce a class
hierarchy — AgentSpec is a plain dataclass, and create_standard_agent()
is a thin wrapper that calls langchain.agents.create_agent with a
canonical middleware chain.

For agents that need a non-standard middleware order (e.g. multi-agent
supervisor, agents with custom pre/post hooks), call create_agent()
directly — this module is opt-in, not mandatory.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Callable

from langchain.agents import create_agent
from langchain.agents.middleware import SummarizationMiddleware
from langgraph.graph.state import CompiledStateGraph

from app.agents.types import AgentRuntimeContext
from app.agents.middleware.prompt import make_dynamic_prompt
from app.agents.middleware.model import dynamic_model
from app.infra.llm import get_system_default_llm

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AgentSpec:
    """Immutable configuration spec for a standard create_agent-based agent.

    Adding a new agent (RAG, research, etc.) requires only defining a
    tools_factory and an agent_id — no copy-paste of middleware chains
    or model instantiation.

    Attributes:
        agent_id: Unique agent identifier (e.g. "chatbot", "rag_agent").
        tools_factory: Zero-argument callable returning the tools list.
            Called once at agent compile time; the return value is cached
            by create_agent() internally.
        prompt_agent_id: Prompt template ID for make_dynamic_prompt().
            Defaults to agent_id (so chatbot uses app/prompts/chatbot.md).
            Override to share prompts across agents (e.g. a RAG agent
            reusing the chatbot prompt).
        context_schema: Dataclass for runtime context injection via
            create_agent()'s context_schema parameter. Defaults to
            AgentRuntimeContext — override for agents that need extra
            fields (e.g. RAG agent adding collection_id).
        enable_summary: Whether to append SummarizationMiddleware to
            trim long conversations automatically.  Default ``True``
            — summarization is opt-out because (a) production
            conversations routinely exceed 4K tokens, (b) the cost
            of a summary call is negligible vs. reprocessing the full
            history on every turn, and (c) the summarization model is
            the system default LLM (not the caller's model), so it
            doesn't consume the caller's rate-limit budget.
        max_tokens_before_summary: Token threshold at which
            SummarizationMiddleware triggers conversation trimming.
            Default 4000 — balances context freshness with
            reasonable memory usage for typical multi-turn sessions.
        messages_to_keep: Number of most recent messages retained
            after summarization truncation.
    """

    agent_id: str
    tools_factory: Callable[[], list]
    prompt_agent_id: str | None = None
    context_schema: type = AgentRuntimeContext
    enable_summary: bool = True
    max_tokens_before_summary: int = 4000
    messages_to_keep: int = 20


def create_standard_agent(
    spec: AgentSpec,
    checkpointer: Any,
    store: Any,
) -> CompiledStateGraph:
    """Create a standard LangChain v1 agent from an AgentSpec.

    Builds the canonical middleware chain executed in order before
    each model call:

    1. **@dynamic_prompt** (make_dynamic_prompt)
       Loads the MD template for ``spec.prompt_agent_id`` (or
       ``spec.agent_id`` if prompt_agent_id is None). Renders time-
       context variables like ``{current_datetime}``, ``{current_date}``,
       etc. Template is cached per agent_id with TTL 300s.

    2. **@wrap_model_call** (dynamic_model)
       Reads ``model_name`` and ``thinking_mode`` from
       ``request.runtime.context`` (the context_schema dataclass).
       Overrides the default LLM via ``get_llm()`` (LiteLLM Router
       with built-in fallback + retry).

    3. **SummarizationMiddleware** (if spec.enable_summary)
       Trims conversation history when total tokens exceed
       ``spec.max_tokens_before_summary``. Keeps the most recent
       ``spec.messages_to_keep`` messages.

    All agents use the system default LLM (from .env, via
    get_system_default_llm()) as the base model. Per-request model
    overrides are handled by the dynamic_model middleware.

    Args:
        spec: Immutable agent specification (see AgentSpec).
        checkpointer: LangGraph checkpointer saver (SqliteSaver or
            AsyncPostgresSaver), injected by the registry at reload time.
        store: LangGraph BaseStore for persistent long-term memory.

    Returns:
        CompiledStateGraph ready for ainvoke / astream_events.
    """
    prompt_id = spec.prompt_agent_id or spec.agent_id
    default_model = get_system_default_llm()
    tools = spec.tools_factory()

    middleware = [
        make_dynamic_prompt(prompt_id),
        dynamic_model,
    ]

    if spec.enable_summary:
        middleware.append(
            SummarizationMiddleware(
                model=default_model,
                trigger=("tokens", spec.max_tokens_before_summary),
                keep=("messages", spec.messages_to_keep),
            )
        )

    logger.info(
        "Creating standard agent: agent_id=%s prompt_id=%s tools=%d "
        "summary=%s trigger=tokens:%d keep=messages:%d",
        spec.agent_id,
        prompt_id,
        len(tools),
        spec.enable_summary,
        spec.max_tokens_before_summary,
        spec.messages_to_keep,
    )

    return create_agent(
        model=default_model,
        tools=tools,
        middleware=middleware,
        checkpointer=checkpointer,
        store=store,
        context_schema=spec.context_schema,
    )
