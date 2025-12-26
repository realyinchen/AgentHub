from dataclasses import dataclass
from langgraph.graph.state import CompiledStateGraph
from langgraph.pregel import Pregel

from app.agents.agentic_rag import rag_agent
from app.agents.hitl_agent import hitl_agent
from app.agents.chatbot import chatbot
from app.schema import AgentInfo

DEFAULT_AGENT = "chatbot"

# Type alias to handle LangGraph's different agent patterns
# - @entrypoint functions return Pregel
# - StateGraph().compile() returns CompiledStateGraph
AgentGraph = CompiledStateGraph | Pregel  # What get_agent() returns (always loaded)


@dataclass
class Agent:
    description: str
    graph: AgentGraph


agents: dict[str, Agent] = {
    "chatbot": Agent(description="A simple chatbot.", graph=chatbot),
    "rag-agent": Agent(
        description="A RAG assistant with access to information in a database.",
        graph=rag_agent,
    ),
    "hitl-agent": Agent(
        description="An agent with Human In The Loop.", graph=hitl_agent
    ),
}


def get_agent(agent_id: str) -> AgentGraph:
    """Get an agent graph"""
    return agents[agent_id].graph


def get_all_agent_info() -> list[AgentInfo]:
    return [
        AgentInfo(agent_id=agent_id, description=agent.description)
        for agent_id, agent in agents.items()
    ]
