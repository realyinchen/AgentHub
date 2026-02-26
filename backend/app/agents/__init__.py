from typing import Dict
from langgraph.graph.state import CompiledStateGraph

from .chatbot import chatbot
from .agentic_rag import rag_agent

agents: Dict[str, CompiledStateGraph] = {
    "chatbot": chatbot,
    "rag-agent": rag_agent,
}
