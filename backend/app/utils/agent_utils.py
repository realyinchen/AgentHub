import logging
from typing import List
from sqlalchemy import select
from langgraph.graph.state import CompiledStateGraph

from app.database import get_database
from app.models.agent import Agent
from app.agents.base import AgentRegistry


logger = logging.getLogger(__name__)

DEFAULT_AGENT_ID = "chatbot"


class AgentNotFound(Exception):
    """Raised when an agent ID is not registered."""

    pass


async def get_available_agent_ids() -> List[str]:
    """Return all active agent IDs from the database."""
    db = get_database()
    async with db.session() as db_session:
        result = await db_session.execute(
            select(Agent.agent_id).where(Agent.is_active.is_(True))
        )
        agent_ids = [row[0] for row in result.all()]
        return agent_ids


async def get_agent(agent_id: str) -> CompiledStateGraph:
    """
    Get an agent by ID.

    The agent uses normal LLM by default. Thinking mode is controlled
    by passing thinking_mode in the config when invoking the agent.

    Args:
        agent_id: The ID of the agent to get

    Returns:
        CompiledStateGraph: The requested agent
    """
    available_agent_ids = await get_available_agent_ids()

    # If no agents in DB, use default
    if not available_agent_ids:
        available_agent_ids = [DEFAULT_AGENT_ID]
        logger.warning(f"No agents in database, using default: {DEFAULT_AGENT_ID}")

    if agent_id not in available_agent_ids:
        raise AgentNotFound(
            f"Agent '{agent_id}' not found. Available agents: {available_agent_ids}",
        )

    # Get agent from registry
    agent = AgentRegistry.get(agent_id)
    if agent is None:
        raise AgentNotFound(
            f"Agent '{agent_id}' is in database but not registered. "
            f"Registered agents: {AgentRegistry.get_all_ids()}",
        )

    logger.info(f"Returning agent: {agent_id}")
    return agent


async def get_available_agents() -> List[CompiledStateGraph]:
    """
    Get all available agents.
    """
    available_agent_ids = await get_available_agent_ids()
    if not available_agent_ids:
        default_agent = AgentRegistry.get(DEFAULT_AGENT_ID)
        return [default_agent] if default_agent else []

    agents = []
    for agent_id in available_agent_ids:
        agent = AgentRegistry.get(agent_id)
        if agent is not None:
            agents.append(agent)
        else:
            logger.warning(
                f"Agent '{agent_id}' is in database but not registered. "
                f"Registered agents: {AgentRegistry.get_all_ids()}"
            )

    return agents