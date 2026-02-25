from langchain_core.messages import HumanMessage
from typing import Any, Dict

from ..state import GraphState


def coordinator(state: GraphState) -> Dict[str, Any]:
    """Extract user question from messages"""

    messages = state["messages"]
    last_message = messages[-1]
    if messages and isinstance(last_message, HumanMessage):
        question = last_message.content
    else:
        question = ""
    
    return {"question": question}
