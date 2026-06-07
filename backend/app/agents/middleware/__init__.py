"""Agent Middleware layer for AgentHub.

The agent middleware layer provides dynamic capabilities injected into agents at runtime:
- memory: short-term (Checkpointer) and long-term (Store) memory
- prompt: runtime prompt service with dynamic injection via @dynamic_prompt
- model: dynamic model selection via @wrap_model_call

This layer sits between infra (foundation) and agents (business logic).

Note: This is NOT a FastAPI HTTP middleware. It is a LangChain agent middleware
layer that wraps model calls, tool calls, and prompt generation within agent
execution. For FastAPI HTTP middleware (CORS, rate limiting, etc.), create a
separate `app/http_middleware/` package.

Architecture (LangChain v1):
    Uses LangChain's official middleware system:
    - @dynamic_prompt: Generates system prompts before each model call
    - @wrap_model_call: Wraps model calls for dynamic model selection, retries, etc.
    - @wrap_tool_call: Wraps tool calls for error handling, logging, etc.

Note:
    The old app.support package has been removed. All functionality now lives in:
    - app.agents.middleware.* (prompt, memory, model agent middleware)
    - app.infra.tools.* (tool implementations)
"""
