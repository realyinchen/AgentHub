"""Receipt-consuming language layer.

Runtime flow:
    ActionPlanner -> SystemRuntime -> PlanReceipt -> Supervisor

The supervisor is initialized once for conversation state and answer
generation. It does not receive direct tools; capability execution is owned by
SystemRuntime.
"""

from app.agents.context import AgentRuntimeContext
from app.agents.supervisor import get_agent, init_agent, is_ready

__all__ = ["init_agent", "get_agent", "is_ready", "AgentRuntimeContext"]
