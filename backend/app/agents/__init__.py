"""Agent layer — Supervisor + self-registering SubAgent architecture.

Architecture (LangChain official Single Dispatch Tool pattern):
    User → Supervisor (checkpointer + dynamic prompt + dynamic model)
                │
                ├── list_agents()  (@tool: discover specialists)
                └── task()         (@tool: delegate to specialist)

Sub-agents self-register via ``@register_subagent`` at import time.
Adding a new subagent only requires a new file in ``subagents/`` —
no supervisor code or prompt changes.

The supervisor is the *only* compiled agent with a checkpointer — it
maintains all multi-turn conversation state. Sub-agents are stateless
one-shot agents called via ``.ainvoke()``.

Startup flow:
    1. ``init_supervisor(checkpointer, store)`` — called once in lifespan.
    2. ``get_supervisor()`` — zero-overhead singleton access at request time.
"""

from app.agents.supervisor import init_supervisor, get_supervisor
from app.agents.context import AgentRuntimeContext

__all__ = [
    "init_supervisor",
    "get_supervisor",
    "AgentRuntimeContext",
]
