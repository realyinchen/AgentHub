from langchain_core.documents import Document
from langchain_tavily import TavilySearch
from typing import Any, Dict, Optional

from ..state import GraphState

# Lazily initialized tool
_web_search_tool: Optional[TavilySearch] = None


def _get_web_search_tool() -> TavilySearch:
    """Get web search tool lazily to avoid import-time errors when API keys are missing."""
    global _web_search_tool
    if _web_search_tool is None:
        _web_search_tool = TavilySearch(max_results=3)
    return _web_search_tool


def web_search(state: GraphState) -> Dict[str, Any]:
    question = state["question"]

    # Initialize documents - this was the missing part!
    documents = state.get("documents", [])  # Get existing documents or empty list

    # Get tool lazily
    tool = _get_web_search_tool()
    
    tavily_results = tool.invoke({"query": question})["results"]
    joined_tavily_result = "\n".join(
        [tavily_result["content"] for tavily_result in tavily_results]
    )
    web_results = Document(page_content=joined_tavily_result)

    # Add web results to existing documents (or create new list if documents was empty)
    if documents:
        documents.append(web_results)
    else:
        documents = [web_results]

    return {"documents": documents, "question": question}