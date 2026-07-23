"""Internal capability operations dispatched only by ``SystemRuntime``.

These implementations retain LangChain tool schemas for validation and
provider adapters, but the receipt-consuming supervisor does not register them
with ``create_agent``. An operation becomes executable only after an ActionPlan
is admitted by the system runtime.
"""

from .time import get_current_time
from .web import create_web_search
from .vectorstore_retriever import vectorstore_search
from .books import (
    get_recommendation_history,
    plan_book_assistant_turn,
    record_book_feedback,
    record_recommendation_signal,
    remember_reading_preference,
    search_books,
)
from .memory import forget_memory, remember_memory, revise_memory, search_memory
from .research import (
    add_evidence,
    analyze_research_data,
    build_recommendation_research_report,
    build_research_observations,
    build_research_report,
    collect_research_sources,
    extract_research_source_records,
    fetch_research_source,
    finalize_research_answer,
    finish_research,
    inspect_research_state,
    plan_recommendation_research_workflow,
    run_recommendation_research_workflow,
    run_research_harness,
    search_research,
    search_research_scholar_sources,
    search_research_sources,
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
    "plan_book_assistant_turn",
    "search_books",
    "get_recommendation_history",
    "remember_reading_preference",
    "record_book_feedback",
    "record_recommendation_signal",
    "start_research",
    "inspect_research_state",
    "search_research",
    "build_recommendation_research_report",
    "plan_recommendation_research_workflow",
    "run_recommendation_research_workflow",
    "analyze_research_data",
    "search_research_scholar_sources",
    "search_research_sources",
    "visit_source",
    "add_evidence",
    "update_research_state",
    "finish_research",
    "build_research_observations",
    "collect_research_sources",
    "extract_research_source_records",
    "fetch_research_source",
    "finalize_research_answer",
    "build_research_report",
    "run_research_harness",
]
