from typing import Any, Dict

from app.tools import retrieve_from_vectorstore
from ..state import GraphState


def retrieve(state: GraphState) -> Dict[str, Any]:
    """Retrieve documents from vector store."""

    question = state["question"]
    _, documents = retrieve_from_vectorstore(
        collection_name="agentic_rag_survey", query=question
    )
    return {"documents": documents, "question": question}
