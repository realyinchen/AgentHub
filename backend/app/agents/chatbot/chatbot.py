"""Chatbot agent with time and web search capabilities."""

import logging

from langchain.agents import create_agent
from langchain.agents.middleware import SummarizationMiddleware
from langchain_core.language_models.fake_chat_models import FakeListChatModel

from app.agents.registry import register_factory
from app.agents.chatbot.types import ChatbotContext
from app.infra.llm import get_chat_litellm, ModelManager
from app.agents.middleware.prompt.dynamic import make_dynamic_prompt
from app.agents.middleware.model.dynamic import dynamic_model
from app.infra.tools.time import get_current_time
from app.infra.tools.web import create_web_search


logger = logging.getLogger(__name__)


# ── Tools ───────────────────────────────────────────────────────────────


def _get_tools():
    """Get tools lazily to avoid import-time errors when API keys are missing.

    Graceful degradation:
    - If web search API key is missing, falls back to time tools only
    """
    try:
        web_search = create_web_search()
        return [get_current_time, web_search]
    except Exception:
        logger.warning(
            "Web search tool initialization failed, falling back to time only"
        )
        return [get_current_time]


# ── Agent Factory ────────────────────────────────────────────────────────


def _create_chatbot_agent(checkpointer=None, store=None):
    """Create and return a compiled chatbot agent using LangChain v1's create_agent.

    This factory is called by reload_agents() at startup (and on DB-triggered
    refresh) with the current checkpointer. The compiled graph is
    cached in memory and reused for every request — no per-request compilation
    overhead.

    The agent uses ChatLiteLLM under the hood (via infra/llm), which supports
    multiple LLM providers through LiteLLM. The actual model is dynamically
    overridden per-request by the @dynamic_model middleware.

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
    # Resolve default model for agent creation.
    # When no model is configured (first-time setup), use a FakeListChatModel
    # as placeholder so the agent compiles and the system can start. Real chat
    # requests will fail until a model is configured via the admin panel.
    default_model_id = ModelManager.get_default_llm_id()
    if default_model_id:
        default_model = get_chat_litellm(default_model_id)
    else:
        logger.warning(
            "No default LLM configured — using FakeListChatModel placeholder. "
            "Chat requests will fail until a real model is added via the admin panel."
        )
        default_model = FakeListChatModel(
            responses=["No model configured. Please add an LLM model in the admin settings."]
        )

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
