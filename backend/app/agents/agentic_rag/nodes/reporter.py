from typing import Any, Dict

from ..state import GraphState


def reporter(state: GraphState) -> Dict[str, Any]:
    """Add the final confirmed answer to messages"""

    generation = state["generation"]
    return {"messages": [generation]}
