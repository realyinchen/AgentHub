from langchain_core.documents import Document
from langgraph.graph import MessagesState
from typing import List


class GraphState(MessagesState):
    """State object for workflow containing query, documents, and control flags."""

    question: str  # User's original query
    generation: str  # LLM-generated response
    web_search: bool  # Control flag for web search requirement
    documents: List[Document]  # Retrieved documents
