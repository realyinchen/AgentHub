"""Prompt middleware for AgentHub.

Provides runtime prompt assembly with dynamic injection of:
- Time / locale context (always, via ChatPromptTemplate variable substitution)
- True IANA timezone conversion via ``zoneinfo.ZoneInfo`` (not just string placeholder)
- Optional template provider (extension point for LangSmith Hub, etc.)

Template resolution priority:
    1. Template provider (e.g. LangSmith pull_prompt) — highest priority
    2. Local MD file (app/prompts/<agent_id>.md) — external source

There is NO built-in fallback. All prompts MUST come from external sources.

Quick start — make_dynamic_prompt factory (recommended):
    from app.agents.middleware.prompt import make_dynamic_prompt

    chatbot_prompt = make_dynamic_prompt("chatbot")
    rag_prompt = make_dynamic_prompt("rag_agent")

    agent = create_agent(
        model=llm,
        tools=tools,
        middleware=[chatbot_prompt, dynamic_model],
    )

Manual usage with @dynamic_prompt:
    from langchain.agents.middleware import dynamic_prompt, ModelRequest
    from app.agents.middleware.prompt import get_prompt_service

    @dynamic_prompt
    def my_agent_prompt(request: ModelRequest) -> str:
        svc = get_prompt_service()
        timezone = getattr(request.runtime.context, "timezone", "Asia/Shanghai")
        return svc.build_system_prompt(
            agent_id="my_agent",
            timezone=timezone,
        )

LangSmith migration:
    from langsmith import Client
    client = Client()
    svc.set_template_provider(lambda aid: client.pull_prompt(aid))

Development:
    # Force reload MD files immediately (bypass TTL cache)
    svc.clear_cache_sync()
"""

from app.agents.middleware.prompt.prompt_builder import PromptService, get_prompt_service
from app.agents.middleware.prompt.prompt_middleware import make_dynamic_prompt

__all__ = [
    "PromptService",
    "get_prompt_service",
    "make_dynamic_prompt",
]
