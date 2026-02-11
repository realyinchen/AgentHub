from typing import Dict
from langgraph.graph.state import CompiledStateGraph

from .chatbot import chatbot
from .agentic_rag import rag_agent
from .hitl_agent import hitl_agent

agents: Dict[str, CompiledStateGraph] = {
    "chatbot": chatbot,
    "rag-agent": rag_agent,
    "hitl-agent": hitl_agent,
}
