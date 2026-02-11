from typing import List
from sqlalchemy import select
from langgraph.graph.state import CompiledStateGraph

from app.database import adb_manager
from app.models.agent import Agent
from app.agents import agents as _AGENTS


DEFAULT_AGENT_ID = "chatbot"


class AgentNotFound(Exception):
    """Raised when an agent ID is not registered."""

    pass


async def get_available_agent_ids() -> List[str]:
    """Return all active agent IDs from the database."""
    async with adb_manager.session() as db:
        result = await db.execute(
            select(Agent.agent_id).where(Agent.is_active.is_(True))
        )
        return [row[0] for row in result.all()]


async def get_agent(agent_id: str) -> CompiledStateGraph:
    """
    Get an agent by ID. Raises HTTPException if agent_id is not available.
    """
    available_agent_ids = await get_available_agent_ids()
    if not available_agent_ids:
        return _AGENTS[DEFAULT_AGENT_ID]
    if agent_id not in available_agent_ids:
        raise AgentNotFound(
            f"Agent '{agent_id}' not found. Available agents: {available_agent_ids}",
        )
    return _AGENTS[agent_id]


async def get_available_agents() -> List[CompiledStateGraph]:
    """
    Get an agent by ID. Raises HTTPException if agent_id is not available.
    """
    available_agent_ids = await get_available_agent_ids()
    if not available_agent_ids:
        return [_AGENTS[DEFAULT_AGENT_ID]]
    return [_AGENTS[agent_id] for agent_id in available_agent_ids]
