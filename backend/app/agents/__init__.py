"""Agent layer — single Agent directly using tools.

Architecture (simplified):
    User → Agent (checkpointer + dynamic prompt + dynamic model)
                │
                ├── get_current_time  (@tool: time queries)
                └── web_search        (@tool: web search)

No subagent delegation — tools are injected directly into the agent.
This eliminates unnecessary LLM calls for routing decisions.

Startup flow:
    1. `await init_agent(checkpointer, store)` — called once in lifespan.
    2. `get_agent()` — zero-overhead singleton access at request time.
"""

from app.agents.supervisor import (
    init_agent,
    get_agent,
    is_ready,
)
from app.agents.context import AgentRuntimeContext

__all__ = [
    "init_agent",
    "get_agent",
    "is_ready",
    "AgentRuntimeContext",
]
