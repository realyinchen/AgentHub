"""Chatbot agent with time and web search capabilities."""

import logging

from langchain.agents import create_agent
from langchain.agents.middleware import SummarizationMiddleware

from app.agents.registry import register_factory
from app.agents.chatbot.types import ChatbotContext
from app.infra.llm import get_system_default_llm
from app.agents.middleware.prompt.prompt_middleware import make_dynamic_prompt
from app.agents.middleware.model.model_middleware import dynamic_model
from app.infra.tools.time import get_current_time
from app.infra.tools.web import create_web_search


logger = logging.getLogger(__name__)


# ── Tools ───────────────────────────────────────────────────────────────

_tools_cache: list | None = None


def _get_tools():
    """Get tools lazily — cached after first successful initialization.

    Graceful degradation:
    - If web search API key is missing, falls back to time tools only
    - Result is cached at module level; agent recompiles always reuse the
      same tool instances.
    """
    global _tools_cache
    if _tools_cache is not None:
        return _tools_cache

    try:
        web_search = create_web_search()
        _tools_cache = [get_current_time, web_search]
    except Exception:
        logger.warning(
            "Web search tool initialization failed, falling back to time only"
        )
        _tools_cache = [get_current_time]
    return _tools_cache


# ── Agent Factory ────────────────────────────────────────────────────────


def _create_chatbot_agent(checkpointer=None, store=None):
    """Create and return a compiled chatbot agent using LangChain v1's create_agent.

    This factory is called by reload_agents() at startup (and on DB-triggered
    refresh) with the current checkpointer. The compiled graph is
    cached in memory and reused for every request — no per-request compilation
    overhead.

    Default model is the system-level LLM (from .env, via get_system_default_llm).
    It is always available — independent of DB / ModelManager — so the agent
    can be compiled and serve requests even before any user-facing model is
    configured. The @dynamic_model middleware overrides it per-request when
    the user explicitly selects a different model from the UI.

    Args:
        checkpointer: LangGraph checkpointer saver (SqliteSaver or
                      AsyncPostgresSaver), injected by the registry at reload time.
        store: (deprecated) LangGraph BaseStore, no longer used for long-term memory.

    Middleware chain (executed before each model call):
        1. chatbot_dynamic_prompt (@dynamic_prompt)
           - Loads app/prompts/chatbot.md (MD template)
           - Renders time-context variables: {current_datetime}, {current_date}, etc.
        2. dynamic_model (@wrap_model_call)
           - Reads model_name and thinking_mode from request.runtime.context
           - Overrides the default LLM via get_llm() (LiteLLM Router with fallback)
        3. SummarizationMiddleware
           - Trims conversation history when messages exceed threshold
           - Trigger: messages > 20, Keep: last 10 messages

    Returns:
        CompiledStateGraph: The compiled chatbot agent.
    """
    # System-level default LLM (from .env). Always available; never None.
    default_model = get_system_default_llm()

    # Create the dynamic prompt middleware for this agent.
    chatbot_dynamic_prompt = make_dynamic_prompt("chatbot")

    # Middleware order matters — they are executed in array order:
    # 1. chatbot_dynamic_prompt — generates system prompt from MD template
    # 2. dynamic_model — overrides model based on context
    # 3. SummarizationMiddleware — trims long conversations
    middleware = [
        chatbot_dynamic_prompt,
        dynamic_model,
        SummarizationMiddleware(
            model=default_model,
            trigger=("messages", 20),
            keep=("messages", 10),
        ),
    ]

    agent = create_agent(
        model=default_model,
        tools=_get_tools(),
        middleware=middleware,
        context_schema=ChatbotContext,
        checkpointer=checkpointer,
    )

    return agent


# ── Register factory ─────────────────────────────────────────────────────

register_factory("chatbot", _create_chatbot_agent)
logger.info("Agent factory registered: chatbot")
