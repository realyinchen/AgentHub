"""Verify the end-to-end flowchart contract without live provider calls.

This is a broad acceptance check for the user-supplied flowchart. It verifies:
- every major dialogue path starts with book-turn-orchestration-v1
- memory update and memory management stay in MemoryOrchestrator
- ordinary recommendations read CurrentMemory, use Book Cache, and suppress read books
- explicit history/explanation turns return suppressed records without fresh search
- Deep Research creates research state/evidence, then report/final answer projections
- researched recommendations fuse candidates with verified research without provider calls
- mem0/gbrain are not used as live transports in this local-first baseline
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
from app.crud.book import create_recommendation_event, upsert_book
from app.infra.database import dispose_database, get_database, init_database
from app.infra.llm.embedding import init_embedding_model
from app.services.recommendation_signals import RecommendationSignalCreate
from app.services.tool_admission import reset_tool_admission_gate
from app.utils.logging import request_id_scope
from app.utils.turn_context import user_message_scope
from scripts.init_database import _init_postgres


BOOK_URL_PREFIX = "https://example.test/flowchart-acceptance/"
FRESH_TITLE = "Flowchart Fresh Novel"
READ_TITLE = "Flowchart Read Novel"
VERIFIED_CLAIM = f"{FRESH_TITLE} is warm and character-driven."


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


async def _json_tool(tool: Any, payload: dict[str, Any]) -> dict[str, Any]:
    return json.loads(await tool.ainvoke(payload))


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
            {"user_id": user_id, "display_name": "Flowchart Acceptance Verify"},
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
                "title": "Flowchart Acceptance Verify",
            },
        )


async def _delete_temp_user(user_id: uuid.UUID) -> None:
    db = get_database()
    async with db.session() as session:
        await session.execute(
            text("DELETE FROM public.users WHERE id = :user_id"),
            {"user_id": user_id},
        )


async def _cleanup_books() -> None:
    db = get_database()
    async with db.session() as session:
        await session.execute(
            text("DELETE FROM public.books WHERE source_url LIKE :pattern"),
            {"pattern": f"{BOOK_URL_PREFIX}%"},
        )


async def _seed_books() -> None:
    db = get_database()
    async with db.session() as session:
        await upsert_book(
            session,
            {
                "title": FRESH_TITLE,
                "authors": ["Acceptance Author"],
                "tags": ["warm", "character-driven", "quiet"],
                "summary": (
                    "A warm character-driven quiet novel used for flowchart "
                    "acceptance."
                ),
                "source_name": "flowchart_cache",
                "source_url": f"{BOOK_URL_PREFIX}fresh",
                "external_id": "flowchart-fresh",
                "raw_data": {"origin": "verify_flowchart_acceptance_flow"},
            },
        )
        await upsert_book(
            session,
            {
                "title": READ_TITLE,
                "authors": ["Acceptance Author"],
                "tags": ["warm", "character-driven", "quiet"],
                "summary": (
                    "A warm character-driven quiet novel that should be "
                    "suppressed as already read."
                ),
                "source_name": "flowchart_cache",
                "source_url": f"{BOOK_URL_PREFIX}read",
                "external_id": "flowchart-read",
                "raw_data": {"origin": "verify_flowchart_acceptance_flow"},
            },
        )


async def _table_count(table: str, user_id: uuid.UUID) -> int:
    db = get_database()
    async with db.session() as session:
        count = await session.scalar(
            text(f"SELECT COUNT(*) FROM public.{table} WHERE user_id = :user_id"),
            {"user_id": user_id},
        )
        return int(count or 0)


async def _research_step_count(user_id: uuid.UUID) -> int:
    db = get_database()
    async with db.session() as session:
        count = await session.scalar(
            text(
                """
                SELECT COUNT(*)
                FROM public.research_steps steps
                JOIN public.research_runs runs ON runs.id = steps.run_id
                WHERE runs.user_id = :user_id
                """
            ),
            {"user_id": user_id},
        )
        return int(count or 0)


async def _evidence_count(user_id: uuid.UUID) -> int:
    db = get_database()
    async with db.session() as session:
        count = await session.scalar(
            text(
                """
                SELECT COUNT(*)
                FROM public.research_evidence evidence
                JOIN public.research_runs runs ON runs.id = evidence.run_id
                WHERE runs.user_id = :user_id
                """
            ),
            {"user_id": user_id},
        )
        return int(count or 0)


async def _seed_read_history(user_id: uuid.UUID, thread_id: uuid.UUID) -> None:
    db = get_database()
    async with db.session() as session:
        await create_recommendation_event(
            session,
            RecommendationSignalCreate(
                user_id=user_id,
                thread_id=thread_id,
                book_title=READ_TITLE,
                event_type="read",
                signal_polarity="neutral",
                signal_strength=1.0,
                source="book_feedback",
                metadata={"origin": "verify_flowchart_acceptance_flow"},
            ),
        )


def _titles(records: list[dict[str, Any]]) -> list[str]:
    return [str(item.get("book_title") or item.get("title") or "") for item in records]


def _contains_memory_value(payload: dict[str, Any], value: str) -> bool:
    needle = value.lower()
    for event in payload.get("relevant_events", []):
        if needle in str(event.get("value", "")).lower():
            return True
    return needle in str(payload.get("profile_summary", "")).lower()


def _assert_no_live_mem0_gbrain(payload: Any) -> None:
    if isinstance(payload, dict):
        provider_sources = payload.get("provider_sources")
        if isinstance(provider_sources, list):
            lowered = {str(item).lower() for item in provider_sources}
            _assert("mem0" not in lowered and "gbrain" not in lowered, str(payload))
        for value in payload.values():
            _assert_no_live_mem0_gbrain(value)
    elif isinstance(payload, list):
        for value in payload:
            _assert_no_live_mem0_gbrain(value)


async def _verify_memory_update_and_search(
    user_id: uuid.UUID,
    thread_id: uuid.UUID,
) -> str:
    memory_before = await _table_count("memory_events", user_id)
    recommendation_before = await _table_count("recommendation_events", user_id)
    research_before = await _table_count("research_runs", user_id)

    reset_tool_admission_gate()
    message = "I like quiet reflective character-driven books."
    with request_id_scope("verify-flowchart-memory-update"):
        with user_message_scope(message):
            plan = await _json_tool(
                book_tools.plan_book_assistant_turn,
                {
                    "user_id": str(user_id),
                    "user_message": message,
                    "query": "quiet reflective character-driven books",
                },
            )
            remembered = await _json_tool(
                memory_tools.remember_memory,
                {
                    "user_id": str(user_id),
                    "thread_id": str(thread_id),
                    "type": "preference",
                    "subject": "style",
                    "value": "quiet reflective character-driven books",
                    "polarity": "like",
                    "source_text": message,
                    "source_kind": "user_message",
                    "metadata": {
                        "origin": "verify_flowchart_acceptance_flow",
                    },
                },
            )
            memory_search = await _json_tool(
                memory_tools.search_memory,
                {
                    "user_id": str(user_id),
                    "thread_id": str(thread_id),
                    "query": "quiet reflective",
                    "limit": 10,
                },
            )

    _assert(plan["route"] == "memory_update", str(plan))
    _assert("remember_memory" in plan["recommended_next_tools"], str(plan))
    _assert(plan["policy"]["can_write_memory"] is True, str(plan["policy"]))
    _assert(remembered.get("id"), str(remembered))
    _assert(
        _contains_memory_value(memory_search, "quiet reflective"),
        str(memory_search),
    )
    _assert(
        await _table_count("memory_events", user_id) == memory_before + 1,
        "memory update should write exactly one memory event",
    )
    _assert(
        await _table_count("recommendation_events", user_id) == recommendation_before,
        "memory update should not write recommendation events",
    )
    _assert(
        await _table_count("research_runs", user_id) == research_before,
        "memory update should not create research state",
    )
    _assert_no_live_mem0_gbrain(memory_search)
    return str(remembered["id"])


async def _verify_ordinary_recommendation(
    user_id: uuid.UUID,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    memory_before = await _table_count("memory_events", user_id)
    recommendation_before = await _table_count("recommendation_events", user_id)
    research_before = await _table_count("research_runs", user_id)

    reset_tool_admission_gate()
    message = "Please recommend warm quiet character-driven books."
    with request_id_scope("verify-flowchart-ordinary-recommendation"):
        with user_message_scope(message):
            plan = await _json_tool(
                book_tools.plan_book_assistant_turn,
                {
                    "user_id": str(user_id),
                    "user_message": message,
                    "query": "warm quiet character-driven books",
                },
            )
            search = await _json_tool(
                book_tools.search_books,
                {
                    "user_id": str(user_id),
                    "query": "warm quiet character-driven books",
                    "limit": 2,
                },
            )

    titles = _titles(search["books"])
    suppressed_titles = _titles(
        search["metadata"]["personalization"].get("suppressed_books", [])
    )
    _assert(plan["route"] == "ordinary_recommendation", str(plan))
    _assert("search_books" in plan["recommended_next_tools"], str(plan))
    _assert(plan["policy"]["can_search_books"] is True, str(plan["policy"]))
    _assert(search["result_mode"] == "ordinary_recommendation", str(search))
    _assert(search["source"] == "book_cache", str(search))
    _assert(FRESH_TITLE in titles, str(search))
    _assert(READ_TITLE not in titles, str(search))
    _assert(READ_TITLE in suppressed_titles, str(search))
    _assert(
        search["books"][0]["candidate_source"]["candidate_source"] == "book_cache",
        str(search["books"][0]),
    )
    _assert(
        search["books"][0]["recommendation_explanation"]["contract_version"]
        == "recommendation-explanation-v1",
        str(search["books"][0]),
    )
    _assert(
        await _table_count("memory_events", user_id) == memory_before,
        "ordinary recommendation should not write memory",
    )
    _assert(
        await _table_count("recommendation_events", user_id) == recommendation_before,
        "ordinary recommendation search should not write recommendation events",
    )
    _assert(
        await _table_count("research_runs", user_id) == research_before,
        "ordinary recommendation should not create research state",
    )
    _assert_no_live_mem0_gbrain(search)
    return list(search["books"]), plan


async def _verify_history_explanation(user_id: uuid.UUID) -> None:
    memory_before = await _table_count("memory_events", user_id)
    recommendation_before = await _table_count("recommendation_events", user_id)
    research_before = await _table_count("research_runs", user_id)

    reset_tool_admission_gate()
    message = f"Why did you not recommend {READ_TITLE}?"
    with request_id_scope("verify-flowchart-history-explanation"):
        with user_message_scope(message):
            plan = await _json_tool(
                book_tools.plan_book_assistant_turn,
                {
                    "user_id": str(user_id),
                    "user_message": message,
                    "query": message,
                    "book_title": READ_TITLE,
                },
            )
            history = await _json_tool(
                book_tools.get_recommendation_history,
                {
                    "user_id": str(user_id),
                    "history_mode": "suppression_explanation",
                    "query": message,
                    "book_title": READ_TITLE,
                    "limit": 10,
                },
            )

    _assert(plan["route"] == "recommendation_history", str(plan))
    _assert(plan["history_mode"] == "suppression_explanation", str(plan))
    _assert("search_books" in plan["policy"]["denied_tools"], str(plan["policy"]))
    _assert(history["result_mode"] == "recommendation_history", str(history))
    _assert(READ_TITLE in _titles(history["suppressed_records"]), str(history))
    _assert(
        history["metadata"]["ordinary_recommendation_candidates"] is False,
        str(history),
    )
    _assert(
        await _table_count("memory_events", user_id) == memory_before,
        "history explanation should not write memory",
    )
    _assert(
        await _table_count("recommendation_events", user_id) == recommendation_before,
        "history explanation should be read-only",
    )
    _assert(
        await _table_count("research_runs", user_id) == research_before,
        "history explanation should not create research state",
    )
    _assert_no_live_mem0_gbrain(history)


async def _verify_deep_research_report(
    user_id: uuid.UUID,
    thread_id: uuid.UUID,
) -> dict[str, Any]:
    memory_before = await _table_count("memory_events", user_id)
    recommendation_before = await _table_count("recommendation_events", user_id)

    reset_tool_admission_gate()
    message = f"Please deep research whether {FRESH_TITLE} fits a warm request."
    with request_id_scope("verify-flowchart-deep-research"):
        with user_message_scope(message):
            plan = await _json_tool(
                book_tools.plan_book_assistant_turn,
                {
                    "user_id": str(user_id),
                    "user_message": message,
                    "query": FRESH_TITLE,
                },
            )
            started = await _json_tool(
                research_tools.start_research,
                {
                    "user_id": str(user_id),
                    "thread_id": str(thread_id),
                    "objective": f"Assess whether {FRESH_TITLE} fits a warm request.",
                    "mode": "deep_research",
                    "subquestions": [
                        f"Is {FRESH_TITLE} warm and character-driven?",
                    ],
                    "next_actions": ["Add source-backed evidence."],
                    "budget": {"required_evidence_quality": "medium"},
                    "stop_criteria": [
                        "At least one medium quality source-backed claim.",
                    ],
                },
            )

            run_id = started["run"]["id"]
            evidence_state = await _json_tool(
                research_tools.add_evidence,
                {
                    "user_id": str(user_id),
                    "run_id": run_id,
                    "claim": VERIFIED_CLAIM,
                    "source_type": "web",
                    "source_title": "Flowchart Reliable Review",
                    "source_url": f"{BOOK_URL_PREFIX}fresh-review",
                    "excerpt": (
                        "The review describes Flowchart Fresh Novel as warm "
                        "and character-driven."
                    ),
                    "quality": "medium",
                    "relevance": 5,
                    "known_facts": [VERIFIED_CLAIM],
                    "next_actions": ["Build a report."],
                    "metadata": {
                        "origin": "verify_flowchart_acceptance_flow",
                    },
                },
            )

    _assert(plan["route"] == "deep_research", str(plan))
    _assert("start_research" in plan["recommended_next_tools"], str(plan))
    _assert(started["run"]["mode"] == "deep_research", str(started))
    _assert(evidence_state["evidence"], str(evidence_state))
    _assert(
        await _table_count("memory_events", user_id) == memory_before,
        "Deep Research should not write long-term memory",
    )
    _assert(
        await _table_count("recommendation_events", user_id) == recommendation_before,
        "Deep Research should not write recommendation events",
    )

    step_before_report = await _research_step_count(user_id)
    evidence_before_report = await _evidence_count(user_id)
    reset_tool_admission_gate()
    report_message = "Please build a research report for this research run."
    with request_id_scope("verify-flowchart-research-report"):
        with user_message_scope(report_message):
            report_plan = await _json_tool(
                book_tools.plan_book_assistant_turn,
                {
                    "user_id": str(user_id),
                    "user_message": report_message,
                    "query": FRESH_TITLE,
                },
            )
            report = await _json_tool(
                research_tools.build_research_report,
                {
                    "user_id": str(user_id),
                    "run_id": started["run"]["id"],
                    "limit_steps": 100,
                    "limit_evidence": 100,
                },
            )
            final_answer = await _json_tool(
                research_tools.finalize_research_answer,
                {
                    "user_id": str(user_id),
                    "run_id": started["run"]["id"],
                    "limit_steps": 100,
                    "limit_evidence": 100,
                },
            )

    _assert(report_plan["route"] == "research_report", str(report_plan))
    _assert(report["result_mode"] == "research_report", str(report))
    _assert(report["contract_version"] == "research-report-v1", str(report))
    _assert(report["report_status"] == "verified", str(report))
    _assert(
        [claim["claim"] for claim in report["verified_claims"]] == [VERIFIED_CLAIM],
        str(report["verified_claims"]),
    )
    _assert(
        final_answer["result_mode"] == "research_final_answer",
        str(final_answer),
    )
    _assert(final_answer["ready_for_final_answer"] is True, str(final_answer))
    _assert(
        await _research_step_count(user_id) == step_before_report,
        "report/final projection should not write research steps",
    )
    _assert(
        await _evidence_count(user_id) == evidence_before_report,
        "report/final projection should not write evidence",
    )
    _assert_no_live_mem0_gbrain(report)
    _assert_no_live_mem0_gbrain(final_answer)
    return report


async def _verify_researched_recommendation(
    user_id: uuid.UUID,
    thread_id: uuid.UUID,
    candidates: list[dict[str, Any]],
    research_report: dict[str, Any],
) -> None:
    memory_before = await _table_count("memory_events", user_id)
    recommendation_before = await _table_count("recommendation_events", user_id)
    research_before = await _table_count("research_runs", user_id)
    evidence_before = await _evidence_count(user_id)

    reset_tool_admission_gate()
    message = "Please deep research and recommend warm character-driven books."
    with request_id_scope("verify-flowchart-researched-recommendation"):
        with user_message_scope(message):
            plan = await _json_tool(
                book_tools.plan_book_assistant_turn,
                {
                    "user_id": str(user_id),
                    "user_message": message,
                    "query": "warm character-driven books",
                    "candidates": candidates,
                    "research_report": research_report,
                },
            )
            runner = await _json_tool(
                research_tools.run_recommendation_research_workflow,
                {
                    "user_id": str(user_id),
                    "thread_id": str(thread_id),
                    "query": "warm character-driven books",
                    "candidates": candidates,
                    "research_report": research_report,
                    "allow_runtime": True,
                },
            )

    _assert(plan["route"] == "researched_recommendation", str(plan))
    _assert(
        plan["recommendation_research_workflow"]["ready_to_fuse"] is True,
        str(plan),
    )
    _assert(
        plan["recommended_next_tools"] == ["build_recommendation_research_report"],
        str(plan),
    )
    _assert(runner["result_mode"] == "recommendation_research_runner", str(runner))
    _assert(runner["status"] == "fused", str(runner))
    _assert(runner["runtime"] is None, str(runner))
    _assert(runner["metadata"]["writes_research_state"] is False, str(runner))
    _assert(runner["metadata"]["writes_evidence"] is False, str(runner))
    _assert(
        runner["recommendation_report"]["result_mode"]
        == "recommendation_research_report",
        str(runner),
    )
    _assert(
        runner["recommendation_report"]["supported_count"] >= 1,
        str(runner["recommendation_report"]),
    )
    _assert(
        await _table_count("memory_events", user_id) == memory_before,
        "researched recommendation fusion should not write memory",
    )
    _assert(
        await _table_count("recommendation_events", user_id) == recommendation_before,
        "researched recommendation fusion should not write recommendation events",
    )
    _assert(
        await _table_count("research_runs", user_id) == research_before,
        "existing-report fusion should not create research runs",
    )
    _assert(
        await _evidence_count(user_id) == evidence_before,
        "existing-report fusion should not write evidence",
    )
    _assert_no_live_mem0_gbrain(runner)


async def _verify_memory_management(user_id: uuid.UUID, memory_id: str) -> None:
    recommendation_before = await _table_count("recommendation_events", user_id)
    research_before = await _table_count("research_runs", user_id)

    reset_tool_admission_gate()
    message = "Forget the quiet reflective preference memory."
    with request_id_scope("verify-flowchart-memory-management"):
        with user_message_scope(message):
            plan = await _json_tool(
                book_tools.plan_book_assistant_turn,
                {
                    "user_id": str(user_id),
                    "user_message": message,
                    "query": "quiet reflective preference memory",
                },
            )
            forgotten = await _json_tool(
                memory_tools.forget_memory,
                {
                    "user_id": str(user_id),
                    "memory_id": memory_id,
                    "reason": "Flowchart acceptance cleanup.",
                },
            )
            memory_search = await _json_tool(
                memory_tools.search_memory,
                {
                    "user_id": str(user_id),
                    "query": "quiet reflective",
                    "limit": 10,
                },
            )

    _assert(plan["route"] == "memory_management", str(plan))
    _assert("forget_memory" in plan["recommended_next_tools"], str(plan))
    _assert(forgotten["forgotten_count"] == 1, str(forgotten))
    _assert(
        not _contains_memory_value(memory_search, "quiet reflective"),
        str(memory_search),
    )
    _assert(
        await _table_count("recommendation_events", user_id) == recommendation_before,
        "memory management should not write recommendation events",
    )
    _assert(
        await _table_count("research_runs", user_id) == research_before,
        "memory management should not create research state",
    )
    _assert_no_live_mem0_gbrain(memory_search)


async def _run_flowchart_acceptance() -> None:
    user_id = uuid.uuid4()
    thread_id = uuid.uuid4()

    await _cleanup_books()
    await _seed_books()
    await _insert_temp_user_and_thread(user_id, thread_id)
    try:
        await _seed_read_history(user_id, thread_id)
        memory_id = await _verify_memory_update_and_search(user_id, thread_id)
        candidates, _ordinary_plan = await _verify_ordinary_recommendation(user_id)
        await _verify_history_explanation(user_id)
        report = await _verify_deep_research_report(user_id, thread_id)
        await _verify_researched_recommendation(
            user_id,
            thread_id,
            candidates,
            report,
        )
        await _verify_memory_management(user_id, memory_id)
    finally:
        await _delete_temp_user(user_id)
        await _cleanup_books()
        reset_tool_admission_gate()


async def _main(skip_migration: bool) -> None:
    load_dotenv()
    if not skip_migration:
        _init_postgres()
    init_embedding_model()
    await init_database()
    try:
        await _run_flowchart_acceptance()
    finally:
        await dispose_database()
    print("flowchart acceptance verification passed")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-migration", action="store_true")
    args = parser.parse_args()

    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(_main(skip_migration=args.skip_migration))


if __name__ == "__main__":
    main()
