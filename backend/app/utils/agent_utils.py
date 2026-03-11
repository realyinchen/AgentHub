from typing import List
from sqlalchemy import select
from langgraph.graph.state import CompiledStateGraph

from app.database import adb_manager
from app.models.agent import Agent
from app.agents.chatbot import chatbot
from app.agents.agentic_rag import rag_agent


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
    
    if agent_id not in available_agent_ids:
        raise AgentNotFound(
            f"Agent '{agent_id}' not found. Available agents: {available_agent_ids}",
        )
    
    # Return the appropriate agent
    # Note: thinking_mode is passed via config at invocation time
    if agent_id == "rag-agent":
        return rag_agent
    else:
        return chatbot


async def get_available_agents() -> List[CompiledStateGraph]:
    """
    Get all available agents.
    """
    available_agent_ids = await get_available_agent_ids()
    if not available_agent_ids:
        return [chatbot]
    
    agents = []
    for agent_id in available_agent_ids:
        if agent_id == "rag-agent":
            agents.append(rag_agent)
        else:
            agents.append(chatbot)
    
    return agents