"""
Verify Phase N ToolAdmissionGate boundaries.

This check avoids network and LLM calls. It verifies:
- tool calls are admitted by app-owned turn policy, not by agent preference
- ordinary recommendation search is limited to one search per turn
- memory writes and forgetting require explicit memory policy flags
- research tools require Deep Search / Deep Research intent
- research tools are not constrained by ordinary recommendation search budgets

Usage:
    cd backend
    .\\.venv\\Scripts\\python.exe scripts\\verify_tool_admission_flow.py
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import uuid
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from sqlalchemy import text

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.agents.tools import books as book_tools
from app.agents.tools import memory as memory_tools
from app.agents.tools import research as research_tools
from app.agents.tools import web as web_tools
from app.infra.database import dispose_database, get_database, init_database
from app.infra.llm.embedding import init_embedding_model
from app.services.book_intent import build_turn_policy
from app.services.book_search import BookSearchCacheResult
from app.services.book_search_contracts import get_book_search_hint
from app.services.external_search import SearchAttempt, SearchResult
from app.services.tool_admission import reset_tool_admission_gate
from app.utils.logging import request_id_scope
from app.utils.turn_context import user_message_scope
from scripts.init_database import _init_postgres


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


class _FakeSessionContext:
    async def __aenter__(self) -> object:
        return object()

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None


class _FakeDatabase:
    def session(self) -> _FakeSessionContext:
        return _FakeSessionContext()


class _FakeBook:
    def __init__(self, title: str) -> None:
        self.id = uuid.uuid4()
        self.title = title
        self.authors = ["Example Author"]
        self.summary = "A warm, character-driven example novel."
        self.rating = None
        self.source_name = "test"
        self.source_url = "https://example.test/book"
        self.external_id = "example-book"


async def _fake_ok_search(
    session,
    *,
    query: str,
    limit: int,
) -> BookSearchCacheResult:
    return BookSearchCacheResult(
        query=query,
        status="ok",
        books=[_FakeBook("Example Novel")],
        source="test",
        next_action_hint=get_book_search_hint("ok"),
        duration_ms=1,
    )


async def _insert_temp_user_and_thread(
    user_id: uuid.UUID,
    thread_id: uuid.UUID,
) -> None:
    db = get_database()
    async with db.session() as session:
        await session.execute(
            text(
                """
                INSERT INTO public.users (id, display_name, is_mock_user)
                VALUES (:user_id, :display_name, true)
                ON CONFLICT (id) DO NOTHING
                """
            ),
            {"user_id": user_id, "display_name": "Tool Admission Verify"},
        )
        await session.execute(
            text(
                """
                INSERT INTO public.conversations (thread_id, user_id, title)
                VALUES (:thread_id, :user_id, :title)
                ON CONFLICT (thread_id) DO NOTHING
                """
            ),
            {
                "thread_id": thread_id,
                "user_id": user_id,
                "title": "Tool Admission Verify",
            },
        )


async def _delete_temp_user(user_id: uuid.UUID) -> None:
    db = get_database()
    async with db.session() as session:
        await session.execute(
            text("DELETE FROM public.users WHERE id = :user_id"),
            {"user_id": user_id},
        )


async def _remember_memory(**payload: Any) -> dict[str, Any]:
    return json.loads(await memory_tools.remember_memory.ainvoke(payload))


async def _forget_memory(**payload: Any) -> dict[str, Any]:
    return json.loads(await memory_tools.forget_memory.ainvoke(payload))


async def _web_search(**payload: Any) -> dict[str, Any]:
    tool = web_tools.create_web_search()
    return json.loads(await tool.ainvoke(payload))


async def _start_research(**payload: Any) -> dict[str, Any]:
    return json.loads(await research_tools.start_research.ainvoke(payload))


async def _search_research(**payload: Any) -> dict[str, Any]:
    return json.loads(await research_tools.search_research.ainvoke(payload))


async def _search_research_sources(**payload: Any) -> dict[str, Any]:
    return json.loads(await research_tools.search_research_sources.ainvoke(payload))


async def _search_research_scholar_sources(**payload: Any) -> dict[str, Any]:
    return json.loads(
        await research_tools.search_research_scholar_sources.ainvoke(payload)
    )


async def _fetch_research_source(**payload: Any) -> dict[str, Any]:
    return json.loads(await research_tools.fetch_research_source.ainvoke(payload))


async def _build_research_report(**payload: Any) -> dict[str, Any]:
    return json.loads(await research_tools.build_research_report.ainvoke(payload))


async def _finalize_research_answer(**payload: Any) -> dict[str, Any]:
    return json.loads(await research_tools.finalize_research_answer.ainvoke(payload))


async def _build_recommendation_research_report(**payload: Any) -> dict[str, Any]:
    return json.loads(
        await research_tools.build_recommendation_research_report.ainvoke(payload)
    )


async def _run_recommendation_research_workflow(**payload: Any) -> dict[str, Any]:
    return json.loads(
        await research_tools.run_recommendation_research_workflow.ainvoke(payload)
    )


async def _build_research_observations(**payload: Any) -> dict[str, Any]:
    return json.loads(await research_tools.build_research_observations.ainvoke(payload))


async def _analyze_research_data(**payload: Any) -> dict[str, Any]:
    return json.loads(await research_tools.analyze_research_data.ainvoke(payload))


async def _extract_research_source_records(**payload: Any) -> dict[str, Any]:
    return json.loads(
        await research_tools.extract_research_source_records.ainvoke(payload)
    )


async def _collect_research_sources(**payload: Any) -> dict[str, Any]:
    return json.loads(await research_tools.collect_research_sources.ainvoke(payload))


async def _run_research_harness(**payload: Any) -> dict[str, Any]:
    return json.loads(await research_tools.run_research_harness.ainvoke(payload))


async def _verify_book_search_admission() -> None:
    original_get_database = book_tools.get_database
    original_search = book_tools.search_and_cache_books_with_status
    search_call_count = 0

    async def counted_search(session, *, query: str, limit: int):
        nonlocal search_call_count
        search_call_count += 1
        return await _fake_ok_search(session, query=query, limit=limit)

    book_tools.get_database = lambda: _FakeDatabase()
    book_tools.search_and_cache_books_with_status = counted_search
    try:
        recommendation_policy = build_turn_policy(
            "Please recommend warm character-driven novels."
        )
        _assert(
            "search_memory" in recommendation_policy.allowed_tools,
            "recommendation turns may read memory",
        )
        _assert(
            "remember_memory" in recommendation_policy.denied_tools,
            "recommendation turns must not advertise memory writes",
        )
        _assert(
            "revise_memory" in recommendation_policy.denied_tools,
            "recommendation turns must not advertise memory revisions",
        )
        _assert(
            "forget_memory" in recommendation_policy.denied_tools,
            "recommendation turns must not advertise memory deletion",
        )

        reset_tool_admission_gate()
        with request_id_scope("phase-n-style-question-blocks-book-search"):
            with user_message_scope(
                "I like Nonviolent Communication. What is this book style?"
            ):
                blocked = json.loads(
                    await book_tools._search_books_impl(
                        "books like Nonviolent Communication",
                        limit=5,
                    )
                )
        _assert(blocked["status"] == "intent_blocked", "style question should block")
        _assert(search_call_count == 0, "blocked search must not call provider")
        admission = blocked["metadata"]["tool_admission"]
        _assert(
            admission["reason"] == "required_policy_flags_missing",
            "blocked search should report missing policy flag",
        )
        _assert(
            "can_search_books" in admission["metadata"]["missing_policy_flags"],
            "book search should require can_search_books",
        )

        reset_tool_admission_gate()
        with request_id_scope("phase-n-ordinary-book-search-budget"):
            with user_message_scope("Please recommend warm character-driven novels."):
                first = json.loads(
                    await book_tools._search_books_impl("warm character novels", limit=3)
                )
                second = json.loads(
                    await book_tools._search_books_impl("gentle family novels", limit=3)
                )
        _assert(first["status"] == "ok", "first ordinary search should be allowed")
        _assert(second["status"] == "loop_detected", "second search should be blocked")
        _assert(
            second["metadata"]["tool_admission"]["reason"] == "tool_budget_exhausted",
            "second search should report budget exhaustion",
        )
    finally:
        book_tools.get_database = original_get_database
        book_tools.search_and_cache_books_with_status = original_search
        reset_tool_admission_gate()


async def _verify_memory_admission(user_id: uuid.UUID) -> None:
    reset_tool_admission_gate()
    with request_id_scope("phase-n-memory-write-blocked"):
        with user_message_scope("What is the style of Nonviolent Communication?"):
            remembered = await _remember_memory(
                user_id=str(user_id),
                type="preference",
                subject="style",
                value="nonviolent communication",
                polarity="like",
                source_text="What is the style of Nonviolent Communication?",
            )
    _assert(remembered["status"] == "tool_blocked", "memory write should block")
    _assert(
        remembered.get("reason") == "precommit_pipeline_required",
        "remember_memory should require the precommit coordinator",
    )

    reset_tool_admission_gate()
    with request_id_scope("phase-n-memory-forget-blocked"):
        with user_message_scope("Please recommend warm character-driven novels."):
            forgotten = await _forget_memory(
                user_id=str(user_id),
                subject="style",
                value="bloody suspense",
                memory_type="preference",
                reason="verify blocked forgetting",
            )
    _assert(forgotten["status"] == "tool_blocked", "forget should block")
    _assert(forgotten["forgotten_count"] == 0, "blocked forget must not delete memory")
    _assert(
        "can_manage_memory"
        in forgotten["tool_admission"]["metadata"]["missing_policy_flags"],
        "forget_memory should require can_manage_memory",
    )

    profile_policy = build_turn_policy("我通常凌晨两点睡，你记一下")
    _assert(
        profile_policy.can_write_memory is True,
        "stable user profile/habit turns may write memory",
    )
    _assert(
        "remember_memory" in profile_policy.denied_tools,
        "legacy agent memory writes must remain denied",
    )

    reset_tool_admission_gate()
    with request_id_scope("phase-n-profile-memory-allowed"):
        with user_message_scope("我通常凌晨两点睡，你记一下"):
            profile_memory = await _remember_memory(
                user_id=str(user_id),
                type="preference",
                subject="user",
                value="sleep routine: usually sleeps around 2am",
                polarity="neutral",
                source_text="我通常凌晨两点睡，你记一下",
            )
    _assert(
        profile_memory.get("status") == "tool_blocked"
        and profile_memory.get("reason") == "precommit_pipeline_required"
        and profile_memory.get("memory") is None,
        "legacy remember_memory must not bypass the precommit coordinator",
    )


async def _verify_web_search_admission() -> None:
    original_gateway = web_tools.get_search_gateway

    class _UnavailableGateway:
        async def search(self, request) -> SearchResult:
            return SearchResult(
                outcome="unavailable",
                query=request.query,
                effective_query=request.query,
                error="verify providers unavailable",
                attempts=[
                    SearchAttempt(
                        provider="tavily",
                        outcome="unavailable",
                        error_type="missing_credentials",
                        error="verify missing Tavily credentials",
                    ),
                    SearchAttempt(
                        provider="anysearch",
                        outcome="unavailable",
                        error_type="provider_error",
                        error="verify AnySearch unavailable",
                    ),
                ],
            )

    web_tools.get_search_gateway = lambda: _UnavailableGateway()
    try:
        policy = build_turn_policy("今天天气怎么样")
        _assert(policy.can_use_web_search is True, "weather may use web_search")
        _assert("web_search" in policy.allowed_tools, "web_search should be allowed")

        general_policy = build_turn_policy("帮我搜一下最近的AI新闻")
        _assert(
            general_policy.can_use_web_search is True,
            "general search requests may use web_search",
        )
        _assert(
            "web_search" in general_policy.allowed_tools,
            "general search should advertise web_search",
        )

        reset_tool_admission_gate()
        with request_id_scope("phase-n-web-search-not-domain-blocked"):
            with user_message_scope("帮我搜一下最近的AI新闻"):
                result = await _web_search(query="最近的AI新闻", max_results=1)
        _assert(
            result["status"] == "completed"
            and result["outcome"] == "unavailable",
            "web_search should reach provider config instead of policy-blocking",
        )
        _assert(
            result["status"] != "tool_blocked",
            "web_search must not be blocked just because the query is non-book",
        )
    finally:
        web_tools.get_search_gateway = original_gateway
        reset_tool_admission_gate()


async def _verify_research_admission(
    user_id: uuid.UUID,
    thread_id: uuid.UUID,
) -> None:
    reset_tool_admission_gate()
    with request_id_scope("phase-n-research-start-blocked"):
        with user_message_scope("What is the style of Nonviolent Communication?"):
            blocked = await _start_research(
                user_id=str(user_id),
                thread_id=str(thread_id),
                objective="Research a style question without explicit deep intent.",
            )
    _assert(blocked["status"] == "tool_blocked", "non-research turn should block")
    _assert(
        "can_start_research"
        in blocked["tool_admission"]["metadata"]["missing_policy_flags"],
        "start_research should require can_start_research",
    )
    reset_tool_admission_gate()
    with request_id_scope("phase-n-research-source-search-blocked"):
        with user_message_scope("What is the style of Nonviolent Communication?"):
            source_search_blocked = await _search_research_sources(
                query="style question source search",
            )
    _assert(
        source_search_blocked["status"] == "tool_blocked",
        "research source search should block outside research turns",
    )
    _assert(
        "can_use_research_tools"
        in source_search_blocked["metadata"]["tool_admission"]["metadata"][
            "missing_policy_flags"
        ],
        "search_research_sources should require can_use_research_tools",
    )
    reset_tool_admission_gate()
    with request_id_scope("phase-n-research-scholar-search-blocked"):
        with user_message_scope("What is the style of Nonviolent Communication?"):
            scholar_search_blocked = await _search_research_scholar_sources(
                query="style question scholarly source search",
            )
    _assert(
        scholar_search_blocked["status"] == "tool_blocked",
        "research scholar search should block outside research turns",
    )
    _assert(
        "can_use_research_tools"
        in scholar_search_blocked["metadata"]["tool_admission"]["metadata"][
            "missing_policy_flags"
        ],
        "search_research_scholar_sources should require can_use_research_tools",
    )
    reset_tool_admission_gate()
    with request_id_scope("phase-n-research-source-visit-blocked"):
        with user_message_scope("What is the style of Nonviolent Communication?"):
            source_visit_blocked = await _fetch_research_source(
                url="https://example.test/blocked",
                query="style question source visit",
            )
    _assert(
        source_visit_blocked["status"] == "tool_blocked",
        "research source visit should block outside research turns",
    )
    _assert(
        "can_use_research_tools"
        in source_visit_blocked["metadata"]["tool_admission"]["metadata"][
            "missing_policy_flags"
        ],
        "fetch_research_source should require can_use_research_tools",
    )
    reset_tool_admission_gate()
    with request_id_scope("phase-n-research-report-blocked"):
        with user_message_scope("What is the style of Nonviolent Communication?"):
            report_blocked = await _build_research_report(
                user_id=str(user_id),
                run_id=str(uuid.uuid4()),
            )
    _assert(
        report_blocked["status"] == "tool_blocked",
        "research report should block outside research turns",
    )
    _assert(
        "can_use_research_tools"
        in report_blocked["tool_admission"]["metadata"]["missing_policy_flags"],
        "build_research_report should require can_use_research_tools",
    )
    reset_tool_admission_gate()
    with request_id_scope("phase-n-research-final-answer-blocked"):
        with user_message_scope("What is the style of Nonviolent Communication?"):
            final_answer_blocked = await _finalize_research_answer(
                user_id=str(user_id),
                run_id=str(uuid.uuid4()),
            )
    _assert(
        final_answer_blocked["status"] == "tool_blocked",
        "research final answer should block outside research turns",
    )
    _assert(
        "can_use_research_tools"
        in final_answer_blocked["metadata"]["tool_admission"]["metadata"][
            "missing_policy_flags"
        ],
        "finalize_research_answer should require can_use_research_tools",
    )
    reset_tool_admission_gate()
    with request_id_scope("phase-n-recommendation-research-report-blocked"):
        with user_message_scope("Please recommend warm books."):
            recommendation_research_blocked = await _build_recommendation_research_report(
                query="warm books",
                candidates=[{"title": "Example Novel"}],
                research_report={"contract_version": "research-report-v1"},
            )
    _assert(
        recommendation_research_blocked["status"] == "tool_blocked",
        "recommendation research report should block outside research turns",
    )
    _assert(
        "can_use_research_tools"
        in recommendation_research_blocked["metadata"]["tool_admission"]["metadata"][
            "missing_policy_flags"
        ],
        "build_recommendation_research_report should require can_use_research_tools",
    )
    reset_tool_admission_gate()
    with request_id_scope("phase-n-recommendation-research-runner-blocked"):
        with user_message_scope("Please recommend warm books."):
            recommendation_runner_blocked = await _run_recommendation_research_workflow(
                user_id=str(user_id),
                query="warm books",
                candidates=[{"title": "Example Novel"}],
                research_report={"contract_version": "research-report-v1"},
            )
    _assert(
        recommendation_runner_blocked["status"] == "tool_blocked",
        "recommendation research runner should block outside research turns",
    )
    _assert(
        "can_use_research_tools"
        in recommendation_runner_blocked["metadata"]["tool_admission"]["metadata"][
            "missing_policy_flags"
        ],
        "run_recommendation_research_workflow should require can_use_research_tools",
    )
    reset_tool_admission_gate()
    with request_id_scope("phase-n-research-observations-blocked"):
        with user_message_scope("What is the style of Nonviolent Communication?"):
            observations_blocked = await _build_research_observations(
                query="style question",
                sources=[
                    {
                        "title": "Blocked Source",
                        "url": "https://example.test/observation-blocked",
                        "claim": "This blocked observation should not normalize.",
                        "excerpt": "Blocked.",
                    }
                ],
            )
    _assert(
        observations_blocked["status"] == "tool_blocked",
        "research observation builder should block outside research turns",
    )
    _assert(
        "can_use_research_tools"
        in observations_blocked["metadata"]["tool_admission"]["metadata"][
            "missing_policy_flags"
        ],
        "build_research_observations should require can_use_research_tools",
    )
    reset_tool_admission_gate()
    with request_id_scope("phase-n-research-python-analysis-blocked"):
        with user_message_scope("What is the style of Nonviolent Communication?"):
            python_analysis_blocked = await _analyze_research_data(
                query="style question supplied data",
                records=[{"title": "Example", "score": 4}],
                dataset_title="Blocked supplied records",
            )
    _assert(
        python_analysis_blocked["status"] == "tool_blocked",
        "research python analysis should block outside research turns",
    )
    _assert(
        "can_use_research_tools"
        in python_analysis_blocked["metadata"]["tool_admission"]["metadata"][
            "missing_policy_flags"
        ],
        "analyze_research_data should require can_use_research_tools",
    )
    _assert(
        python_analysis_blocked["metadata"]["executes_user_code"] is False,
        "blocked python analysis payload should declare no code execution",
    )
    reset_tool_admission_gate()
    with request_id_scope("phase-n-research-source-extraction-blocked"):
        with user_message_scope("What is the style of Nonviolent Communication?"):
            source_extraction_blocked = await _extract_research_source_records(
                query="style question",
                documents=[
                    {
                        "title": "Blocked Source",
                        "url": "https://example.test/source-extraction-blocked",
                        "content": "Blocked Source says extraction should not run.",
                    }
                ],
            )
    _assert(
        source_extraction_blocked["status"] == "tool_blocked",
        "research source extraction should block outside research turns",
    )
    _assert(
        "can_use_research_tools"
        in source_extraction_blocked["metadata"]["tool_admission"]["metadata"][
            "missing_policy_flags"
        ],
        "extract_research_source_records should require can_use_research_tools",
    )
    reset_tool_admission_gate()
    with request_id_scope("phase-n-research-source-collection-blocked"):
        with user_message_scope("What is the style of Nonviolent Communication?"):
            source_collection_blocked = await _collect_research_sources(
                user_id=str(user_id),
                run_id=str(uuid.uuid4()),
                query="style question",
                sources=[
                    {
                        "title": "Blocked Source",
                        "url": "https://example.test/source-collection-blocked",
                        "claim": "This blocked source should not be collected.",
                        "excerpt": "Blocked.",
                    }
                ],
            )
    _assert(
        source_collection_blocked["status"] == "tool_blocked",
        "research source collection should block outside research turns",
    )
    _assert(
        "can_use_research_tools"
        in source_collection_blocked["metadata"]["tool_admission"]["metadata"][
            "missing_policy_flags"
        ],
        "collect_research_sources should require can_use_research_tools",
    )
    reset_tool_admission_gate()
    with request_id_scope("phase-n-research-runtime-blocked"):
        with user_message_scope("What is the style of Nonviolent Communication?"):
            runtime_blocked = await _run_research_harness(
                user_id=str(user_id),
                thread_id=str(thread_id),
                objective="Runtime should not run for a non-research turn.",
                observations=[
                    {
                        "source_type": "web",
                        "source_title": "Blocked Source",
                        "source_url": "https://example.test/runtime-blocked",
                        "claim": "This blocked claim should not be stored.",
                        "excerpt": "Blocked.",
                        "quality": "medium",
                        "relevance": 4,
                        "metadata": {"provider_source": "tool_admission_verify"},
                    }
                ],
            )
    _assert(
        runtime_blocked["status"] == "tool_blocked",
        "research runtime should block outside research turns",
    )
    _assert(
        "can_start_research"
        in runtime_blocked["tool_admission"]["metadata"]["missing_policy_flags"],
        "run_research_harness should require can_start_research",
    )

    original_source_search = research_tools.search_research_source_documents_result
    original_scholar_search = research_tools.search_research_scholar_documents_result
    original_source_visit = research_tools.fetch_research_source_document_result

    class _FakeSourceSearchResult:
        def model_dump(self, mode: str = "json") -> dict[str, Any]:
            return {
                "result_mode": "research_source_search",
                "contract_version": "research-source-search-v1",
                "status": "ok",
                "query": "Example Novel source-backed review",
                "subquestion": "Is Example Novel source-backed?",
                "provider_name": "duckduckgo",
                "provider_query": "Example Novel source-backed review",
                "source_documents": [
                    {
                        "source_type": "web",
                        "source_title": "Source Search Result",
                        "source_url": "https://example.test/source-search",
                        "content": "Example Novel is supported by a reliable review.",
                        "quality": "medium",
                        "relevance": 5,
                        "metadata": {"provider_source": "tool_admission_verify"},
                    }
                ],
                "extraction": {
                    "result_mode": "research_source_extraction",
                    "contract_version": "research-source-extraction-v1",
                    "status": "ok",
                    "query": "Example Novel source-backed review",
                    "subquestion": "Is Example Novel source-backed?",
                    "source_records": [
                        {
                            "source_type": "web",
                            "source_title": "Source Search Result",
                            "source_url": "https://example.test/source-search",
                            "claim": "Example Novel is supported by a reliable review.",
                            "excerpt": "Example Novel is supported by a reliable review.",
                            "quality": "medium",
                            "relevance": 5,
                            "metadata": {"provider_source": "tool_admission_verify"},
                        }
                    ],
                    "observation_batch": None,
                    "rejected_documents": [],
                    "document_count": 1,
                    "extracted_count": 1,
                    "metadata": {"external_call": False},
                },
                "document_count": 1,
                "extracted_count": 1,
                "error": None,
                "duration_ms": 1,
                "metadata": {
                    "writes_research_state": False,
                    "writes_evidence": False,
                    "writes_long_term_memory": False,
                    "writes_recommendation_events": False,
                    "external_call": True,
                },
            }

    async def fake_source_search(**payload: Any) -> _FakeSourceSearchResult:
        return _FakeSourceSearchResult()

    class _FakeScholarSearchResult:
        def model_dump(self, mode: str = "json") -> dict[str, Any]:
            return {
                "result_mode": "research_scholar_search",
                "contract_version": "research-scholar-search-v1",
                "status": "ok",
                "query": "Example Novel scholarly source-backed review",
                "subquestion": "Is Example Novel source-backed by papers?",
                "provider_name": "crossref",
                "provider_query": "Example Novel scholarly source-backed review",
                "source_documents": [
                    {
                        "source_type": "paper",
                        "source_title": "Scholar Search Result",
                        "source_url": "https://doi.org/10.5555/tool-admission",
                        "content": "Example Novel is supported by a scholarly paper.",
                        "quality": "medium",
                        "relevance": 5,
                        "metadata": {"provider_source": "tool_admission_verify"},
                    }
                ],
                "extraction": {
                    "result_mode": "research_source_extraction",
                    "contract_version": "research-source-extraction-v1",
                    "status": "ok",
                    "query": "Example Novel scholarly source-backed review",
                    "subquestion": "Is Example Novel source-backed by papers?",
                    "source_records": [
                        {
                            "source_type": "paper",
                            "source_title": "Scholar Search Result",
                            "source_url": "https://doi.org/10.5555/tool-admission",
                            "claim": "Example Novel is supported by a scholarly paper.",
                            "excerpt": "Example Novel is supported by a scholarly paper.",
                            "quality": "medium",
                            "relevance": 5,
                            "metadata": {"provider_source": "tool_admission_verify"},
                        }
                    ],
                    "observation_batch": None,
                    "rejected_documents": [],
                    "document_count": 1,
                    "extracted_count": 1,
                    "metadata": {"external_call": False},
                },
                "document_count": 1,
                "extracted_count": 1,
                "error": None,
                "duration_ms": 1,
                "metadata": {
                    "writes_research_state": False,
                    "writes_evidence": False,
                    "writes_long_term_memory": False,
                    "writes_recommendation_events": False,
                    "external_call": True,
                },
            }

    async def fake_scholar_search(**payload: Any) -> _FakeScholarSearchResult:
        return _FakeScholarSearchResult()

    class _FakeSourceVisitResult:
        def model_dump(self, mode: str = "json") -> dict[str, Any]:
            return {
                "result_mode": "research_source_visit",
                "contract_version": "research-source-visit-v1",
                "status": "ok",
                "url": "https://example.test/source-visit",
                "final_url": "https://example.test/source-visit",
                "query": "Example Novel source-backed review",
                "subquestion": "Is Example Novel source-backed?",
                "source_document": {
                    "source_type": "web",
                    "source_title": "Visited Source",
                    "source_url": "https://example.test/source-visit",
                    "content": "Example Novel is supported by a reliable review.",
                    "quality": "unknown",
                    "relevance": 5,
                    "metadata": {"provider_source": "tool_admission_verify"},
                },
                "extraction": {
                    "result_mode": "research_source_extraction",
                    "contract_version": "research-source-extraction-v1",
                    "status": "ok",
                    "query": "Example Novel source-backed review",
                    "subquestion": "Is Example Novel source-backed?",
                    "source_records": [
                        {
                            "source_type": "web",
                            "source_title": "Visited Source",
                            "source_url": "https://example.test/source-visit",
                            "claim": "Example Novel is supported by a reliable review.",
                            "excerpt": "Example Novel is supported by a reliable review.",
                            "quality": "unknown",
                            "relevance": 5,
                            "metadata": {"provider_source": "tool_admission_verify"},
                        }
                    ],
                    "observation_batch": None,
                    "rejected_documents": [],
                    "document_count": 1,
                    "extracted_count": 1,
                    "metadata": {"external_call": False},
                },
                "extracted_count": 1,
                "error": None,
                "duration_ms": 1,
                "metadata": {
                    "writes_research_state": False,
                    "writes_evidence": False,
                    "writes_long_term_memory": False,
                    "writes_recommendation_events": False,
                    "external_call": True,
                },
            }

    async def fake_source_visit(**payload: Any) -> _FakeSourceVisitResult:
        return _FakeSourceVisitResult()

    research_tools.search_research_source_documents_result = fake_source_search
    research_tools.search_research_scholar_documents_result = fake_scholar_search
    research_tools.fetch_research_source_document_result = fake_source_visit
    try:
        reset_tool_admission_gate()
        with request_id_scope("phase-n-research-tools-not-book-budgeted"):
            with user_message_scope(
                "Please deep research warm communication books and compare evidence."
            ):
                started = await _start_research(
                    user_id=str(user_id),
                    thread_id=str(thread_id),
                    objective="Deep research warm communication books.",
                    subquestions=["Which books are warm and communication-oriented?"],
                    gaps=["Need source-backed candidate facts."],
                    next_actions=["Search two distinct evidence points."],
                    budget={"max_steps": 5},
                    stop_criteria=["Two research search steps recorded."],
                )
                run_id = started["run"]["id"]
                first = await _search_research(
                    user_id=str(user_id),
                    run_id=run_id,
                    query="warm communication books source one",
                    status="completed",
                    rationale="First research query.",
                    results=[{"title": "Source One", "url": "https://example.test/one"}],
                    next_actions=["Search a second evidence point."],
                )
                second = await _search_research(
                    user_id=str(user_id),
                    run_id=run_id,
                    query="warm communication books source two",
                    status="completed",
                    rationale="Second research query.",
                    results=[{"title": "Source Two", "url": "https://example.test/two"}],
                    next_actions=["Aggregate evidence."],
                )
                source_search = await _search_research_sources(
                    query="Example Novel source-backed review",
                    subquestion="Is Example Novel source-backed?",
                    limit=3,
                )
                scholar_search = await _search_research_scholar_sources(
                    query="Example Novel scholarly source-backed review",
                    subquestion="Is Example Novel source-backed by papers?",
                    limit=3,
                )
                source_visit = await _fetch_research_source(
                    url="https://example.test/source-visit",
                    query="Example Novel source-backed review",
                    subquestion="Is Example Novel source-backed?",
                )
                report = await _build_research_report(
                    user_id=str(user_id),
                    run_id=run_id,
                )
                final_answer = await _finalize_research_answer(
                    user_id=str(user_id),
                    run_id=run_id,
                )
                recommendation_research_report = await (
                    _build_recommendation_research_report(
                        query="Example Novel source-backed recommendation",
                        candidates=[
                            {
                                "id": str(uuid.uuid4()),
                                "title": "Example Novel",
                                "authors": ["Example Author"],
                                "summary": "A warm, source-backed candidate.",
                                "recommendation": {
                                    "score": 1.4,
                                    "suppressed": False,
                                    "positive_reasons": ["matches warm preference"],
                                    "suppression_reasons": [],
                                    "metadata": {
                                        "contract_version": (
                                            "recommendation-projection-v1"
                                        )
                                    },
                                },
                                "recommendation_explanation": {
                                    "contract_version": "recommendation-explanation-v1",
                                    "positive_reasons": ["matches warm preference"],
                                },
                            }
                        ],
                        research_report={
                            "contract_version": "research-report-v1",
                            "run_id": run_id,
                            "report_status": "verified",
                            "verified_claims": [
                                {
                                    "claim": (
                                        "Example Novel is supported by a reliable "
                                        "review."
                                    ),
                                    "evidence_ids": [str(uuid.uuid4())],
                                    "reason_codes": [],
                                    "confidence": 1.0,
                                }
                            ],
                            "uncertain_claims": [],
                            "rejected_claims": [],
                            "sources": [
                                {
                                    "evidence_id": str(uuid.uuid4()),
                                    "source_type": "web",
                                    "source_title": "Reliable Review",
                                    "source_url": "https://example.test/reliable",
                                    "quality": "medium",
                                    "relevance": 5,
                                    "claim": (
                                        "Example Novel is supported by a reliable "
                                        "review."
                                    ),
                                }
                            ],
                        },
                    )
                )
                observation_batch = await _build_research_observations(
                    query="Example Novel source-backed review",
                    subquestion="Is Example Novel source-backed?",
                    provider_source="tool_admission_verify",
                    sources=[
                        {
                            "title": "Harness Source",
                            "url": "https://example.test/harness-source",
                            "claim": "Example Novel is supported by a reliable review.",
                            "excerpt": "The review gives a source-backed claim.",
                            "quality": "medium",
                            "relevance": 5,
                        }
                    ],
                )
                python_analysis = await _analyze_research_data(
                    query="Analyze supplied recommendation evidence scores",
                    subquestion="Which supplied score is strongest?",
                    dataset_title="Tool admission supplied analysis records",
                    source_type="manual",
                    records=[
                        {"candidate": "Example Novel", "score": 4.8, "status": "kept"},
                        {"candidate": "Other Novel", "score": 3.2, "status": "filtered"},
                        {"candidate": "Third Novel", "score": 4.1, "status": "kept"},
                    ],
                    focus_fields=["score", "status"],
                )
                source_extraction = await _extract_research_source_records(
                    query="Example Novel source-backed review",
                    subquestion="Is Example Novel source-backed?",
                    provider_source="tool_admission_verify",
                    documents=[
                        {
                            "title": "Extracted Source",
                            "url": "https://example.test/extracted-source",
                            "content": (
                                "Example Novel is supported by a reliable review. "
                                "The source discusses its recommendation fit."
                            ),
                            "quality": "medium",
                            "relevance": 5,
                        }
                    ],
                )
                source_collection = await _collect_research_sources(
                    user_id=str(user_id),
                    run_id=run_id,
                    query="Example Novel source-backed review",
                    subquestion="Is Example Novel source-backed?",
                    provider_source="tool_admission_verify",
                    sources=[
                        {
                            "title": "Harness Source",
                            "url": "https://example.test/harness-source",
                            "claim": "Example Novel is supported by a reliable review.",
                            "excerpt": "The review gives a source-backed claim.",
                            "quality": "medium",
                            "relevance": 5,
                        }
                    ],
                )
                runtime = await _run_research_harness(
                    user_id=str(user_id),
                    thread_id=str(thread_id),
                    objective="Run a local research harness pass.",
                    subquestions=["Is Example Novel source-backed?"],
                    gaps=["Need source-backed evidence."],
                    next_actions=["Run harness."],
                    budget={"required_evidence_quality": "medium"},
                    stop_criteria=["One medium-quality claim is admitted."],
                    observations=observation_batch["observations"],
                )
                recommendation_runner = await _run_recommendation_research_workflow(
                    user_id=str(user_id),
                    thread_id=str(thread_id),
                    query="Example Novel source-backed recommendation",
                    candidates=[
                        {
                            "id": str(uuid.uuid4()),
                            "title": "Example Novel",
                            "authors": ["Example Author"],
                            "summary": "A warm, source-backed candidate.",
                            "recommendation": {
                                "score": 1.4,
                                "suppressed": False,
                                "positive_reasons": ["matches warm preference"],
                                "suppression_reasons": [],
                            },
                        }
                    ],
                    observations=observation_batch["observations"],
                    subquestions=["Is Example Novel source-backed?"],
                    gaps=["Need source-backed evidence."],
                    next_actions=["Run researched recommendation workflow."],
                    budget={"required_evidence_quality": "medium"},
                    stop_criteria=["One medium-quality claim is admitted."],
                )
    finally:
        research_tools.search_research_source_documents_result = original_source_search
        research_tools.search_research_scholar_documents_result = original_scholar_search
        research_tools.fetch_research_source_document_result = original_source_visit
    _assert(started["run"]["status"] == "active", "research should start")
    _assert(first["state"]["status"] == "active", "first research search should pass")
    _assert(second["state"]["status"] == "active", "second research search should pass")
    _assert(
        source_search["result_mode"] == "research_source_search",
        "research source search should be allowed",
    )
    _assert(
        scholar_search["result_mode"] == "research_scholar_search",
        "research scholar search should be allowed",
    )
    _assert(
        source_visit["result_mode"] == "research_source_visit",
        "research source visit should be allowed",
    )
    _assert(report["result_mode"] == "research_report", "report should be allowed")
    _assert(
        final_answer["result_mode"] == "research_final_answer",
        "research final answer should be allowed",
    )
    _assert(
        recommendation_research_report["result_mode"]
        == "recommendation_research_report",
        "recommendation research report should be allowed",
    )
    _assert(
        recommendation_research_report["recommended_candidates"],
        "recommendation research report should support a matched candidate",
    )
    _assert(
        observation_batch["result_mode"] == "research_observation_batch",
        "research observation batch should be allowed",
    )
    _assert(
        observation_batch["observation_count"] == 1,
        "research observation batch should normalize sources",
    )
    _assert(
        python_analysis["result_mode"] == "research_python_analysis",
        "research python analysis should be allowed",
    )
    _assert(
        python_analysis["metadata"]["executes_user_code"] is False,
        "research python analysis should not execute user code",
    )
    _assert(
        python_analysis["observation_batch"]["observation_count"] >= 1,
        "research python analysis should produce observations",
    )
    _assert(
        source_extraction["result_mode"] == "research_source_extraction",
        "research source extraction should be allowed",
    )
    _assert(
        source_extraction["observation_batch"]["observation_count"] == 1,
        "research source extraction should create observations",
    )
    _assert(
        source_collection["result_mode"] == "research_source_collection",
        "research source collection should be allowed",
    )
    _assert(
        source_collection["observation_batch"]["observation_count"] == 1,
        "research source collection should normalize accepted source records",
    )
    _assert(
        runtime["result_mode"] == "research_runtime",
        "research runtime should be allowed",
    )
    _assert(
        runtime["report"]["result_mode"] == "research_report",
        "research runtime should return a nested report",
    )
    _assert(
        recommendation_runner["result_mode"] == "recommendation_research_runner",
        "recommendation research runner should be allowed",
    )
    _assert(
        recommendation_runner["recommendation_report"]["result_mode"]
        == "recommendation_research_report",
        "recommendation research runner should return a fused report",
    )
    _assert(
        len([step for step in second["steps"] if step["step_type"] == "search"]) >= 2,
        "research tools should allow repeated search-state updates",
    )


async def _run_tool_admission_flow() -> None:
    user_id = uuid.uuid4()
    thread_id = uuid.uuid4()

    await _insert_temp_user_and_thread(user_id, thread_id)
    try:
        await _verify_book_search_admission()
        await _verify_memory_admission(user_id)
        await _verify_web_search_admission()
        await _verify_research_admission(user_id, thread_id)
        print("tool admission verification passed")
        print(f"user_id={user_id}")
        print(f"thread_id={thread_id}")
    finally:
        await _delete_temp_user(user_id)


async def _main(skip_migration: bool) -> None:
    load_dotenv()
    if not skip_migration:
        _init_postgres()
    init_embedding_model()
    await init_database()
    try:
        await _run_tool_admission_flow()
    finally:
        await dispose_database()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--skip-migration",
        action="store_true",
        help="Skip SQL migration and only run behavior checks.",
    )
    args = parser.parse_args()

    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(_main(skip_migration=args.skip_migration))


if __name__ == "__main__":
    main()
