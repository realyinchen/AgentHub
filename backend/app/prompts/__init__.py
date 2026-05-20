"""Agent prompt templates (MD files).

This directory contains system prompt templates for each agent, stored as
Markdown files named by ``agent_id``::

    app/prompts/
    ├── __init__.py
    ├── chatbot.md      # Chatbot agent prompt
    ├── rag_agent.md    # RAG agent prompt (future)
    └── ...

Templates are loaded at runtime by ``PromptService`` via
``app.agents.middleware.prompt.get_prompt_service()``.  They support
``{variable}`` placeholders that are substituted on each request
(e.g. ``{current_datetime}``, ``{timezone}``).

Do NOT import from this package directly — use the PromptService API::

    from app.agents.middleware.prompt import get_prompt_service

    svc = get_prompt_service()
    prompt = svc.build_system_prompt(agent_id="chatbot", store=store, user_id=user_id)
"""
