"""Agent tools for AgentHub.

Shared tools that agents use to interact with the world.
Located at app/agents/tools/ — tools are part of the agent layer
and injected into agents via create_agent(tools=[...]).

Available tools:
- time: Current time in any timezone
- web: Web search via Tavily
- vectorstore_retriever: Semantic search over vector store
"""

from .time import get_current_time
from .web import create_web_search
from .vectorstore_retriever import vectorstore_search
from .books import (
    record_book_feedback,
    record_recommendation_signal,
    remember_reading_preference,
    search_books,
)
from .memory import search_memory, remember_memory, revise_memory, forget_memory
from .research import (
    add_evidence,
    finish_research,
    inspect_research_state,
    search_research,
    start_research,
    update_research_state,
    visit_source,
)

__all__ = [
    "get_current_time",
    "create_web_search",
    "vectorstore_search",
    "search_memory",
    "remember_memory",
    "revise_memory",
    "forget_memory",
    "search_books",
    "remember_reading_preference",
    "record_book_feedback",
    "record_recommendation_signal",
    "start_research",
    "inspect_research_state",
    "search_research",
    "visit_source",
    "add_evidence",
    "update_research_state",
    "finish_research",
]
