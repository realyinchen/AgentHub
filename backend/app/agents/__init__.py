"""Agent registry and chatbot agent exports.

All agents in this project use LangChain v1's create_agent API with middleware.
Each agent module calls register_factory() at module level to declare its
compile-time factory. reload_agents() compiles all active agents at startup.

See app.agents.registry for the registry infrastructure.
See app.agents.chatbot for the chatbot agent implementation.
"""

import importlib
import pkgutil

from app.agents.registry import (
    AgentNotFoundError,
    register_factory,
    reload_agent,
    reload_agents,
    get_graph,
    require_graph,
    get_metadata,
    list_metadata,
    get_ids,
    get_snapshot_size,
)

# ── Auto-discover agent modules ────────────────────────────────────────
# Each agent subpackage (e.g. chatbot/) calls register_factory() at module
# level. Importing them triggers those side-effects so the factory dict is
# populated before reload_agents() runs at startup.
# Non-agent subpackages (e.g. middleware/) are imported harmlessly —
# they don't call register_factory().
for _, name, _ in pkgutil.iter_modules(__path__):
    importlib.import_module(f"{__name__}.{name}")

__all__ = [
    "AgentNotFoundError",
    "register_factory",
    "reload_agent",
    "reload_agents",
    "get_graph",
    "require_graph",
    "get_metadata",
    "list_metadata",
    "get_ids",
    "get_snapshot_size",
]
