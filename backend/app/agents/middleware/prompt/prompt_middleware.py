"""Dynamic prompt middleware factory using LangChain v1's @dynamic_prompt.

Provides ``make_dynamic_prompt(agent_id)`` — a factory that creates a
``@dynamic_prompt`` middleware for any agent. This replaces the old
hardcoded ``chatbot_dynamic_prompt`` pattern.

Follows the official LangChain v1 pattern:
    https://docs.langchain.com/oss/python/langchain/agents#dynamic-prompt

Usage::

    from app.agents.middleware.prompt.prompt_middleware import make_dynamic_prompt

    # One line per agent — no need to write separate functions
    chatbot_prompt = make_dynamic_prompt("chatbot")
    rag_prompt = make_dynamic_prompt("rag_agent")

    # Use in create_agent middleware list
    from langchain.agents import create_agent

    agent = create_agent(
        model=llm,
        tools=tools,
        middleware=[chatbot_prompt, ...],
    )
"""

import logging

from langchain.agents.middleware import dynamic_prompt, ModelRequest

from app.agents.middleware.prompt.prompt_builder import get_prompt_service

logger = logging.getLogger(__name__)


def make_dynamic_prompt(
    agent_id: str,
    default_timezone: str = "Asia/Shanghai",
):
    """Create a ``@dynamic_prompt`` middleware for the given agent.

    This factory generates a function that:
    1. Reads ``timezone`` from ``request.runtime.context``
    2. Calls ``PromptService.build_system_prompt()`` which:
       - Loads the MD template from ``app/prompts/<agent_id>.md``
       - Renders time-context variables (``{current_datetime}``, etc.)

    The resulting function is decorated with ``@dynamic_prompt`` so
    LangChain's agent runtime calls it before each model call.

    Args:
        agent_id: The agent's identifier — must match an MD file in
            ``app/prompts/<agent_id>.md`` or a template provider entry.
        default_timezone: Fallback IANA timezone when context has none.
            Defaults to ``"Asia/Shanghai"``.

    Returns:
        A ``@dynamic_prompt``-decorated function, ready for the
        ``middleware=`` list in ``create_agent()``.

    Example::

        chatbot_prompt = make_dynamic_prompt("chatbot")
        rag_prompt = make_dynamic_prompt("rag_agent", default_timezone="UTC")

        agent = create_agent(
            model=llm,
            tools=tools,
            middleware=[chatbot_prompt, dynamic_model],
        )
    """

    @dynamic_prompt
    def _dynamic_prompt(request: ModelRequest) -> str:
        """Generate system prompt before each model call.

        Reads ``timezone`` from the runtime context (dataclass attribute access)
        and assembles the MD template with time-context substitution.

        Per the LangChain v1 official pattern, all agents in this project MUST
        use a ``@dataclass`` for ``context_schema`` — dict / TypedDict contexts
        are not supported.
        """
        svc = get_prompt_service()

        timezone = default_timezone
        if request.runtime is not None and request.runtime.context is not None:
            tz = getattr(request.runtime.context, "timezone", None)
            if tz:
                timezone = tz

        return svc.build_system_prompt(
            agent_id=agent_id,
            timezone=timezone,
        )

    return _dynamic_prompt