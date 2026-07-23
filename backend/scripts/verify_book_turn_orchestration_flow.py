"""Verify Phase P33 book assistant turn orchestration.

This check avoids live web/LLM calls. It verifies:
- plan_book_assistant_turn is a read-only entry route contract
- ordinary recommendation, history/explanation, researched recommendation,
  Deep Research, and answer-only turns route to the expected next tools
- researched recommendation routing nests recommendation-research-workflow-v1
- the router writes no memory, recommendation events, research runs, or evidence
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
from app.infra.database import dispose_database, get_database, init_database
from app.infra.llm.embedding import init_embedding_model
from app.services.memory.contracts import MemoryCandidate
from app.services.memory.orchestrator import get_memory_orchestrator
from app.services.tool_admission import reset_tool_admission_gate
from app.utils.logging import request_id_scope
from app.utils.turn_context import user_message_scope
from scripts.init_database import _init_postgres


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


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
            {"user_id": user_id, "display_name": "Book Turn Orchestration Verify"},
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
                "title": "Book Turn Orchestration Verify",
            },
        )


async def _delete_temp_user(user_id: uuid.UUID) -> None:
    db = get_database()
    async with db.session() as session:
        await session.execute(
            text("DELETE FROM public.users WHERE id = :user_id"),
            {"user_id": user_id},
        )


async def _table_count(table: str, user_id: uuid.UUID) -> int:
    db = get_database()
    async with db.session() as session:
        count = await session.scalar(
            text(f"SELECT COUNT(*) FROM public.{table} WHERE user_id = :user_id"),
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


async def _plan_turn(**payload: Any) -> dict[str, Any]:
    return json.loads(await book_tools.plan_book_assistant_turn.ainvoke(payload))


def _candidate(title: str, *, suppressed: bool = False) -> dict[str, Any]:
    reasons = ["already_read"] if suppressed else []
    return {
        "id": str(uuid.uuid4()),
        "title": title,
        "authors": ["Example Author"],
        "summary": "A warm, quiet, character-driven novel.",
        "recommendation": {
            "score": 1.2,
            "suppressed": suppressed,
            "positive_reasons": ["matches current memory"],
            "suppression_reasons": reasons,
        },
        "recommendation_explanation": {
            "contract_version": "recommendation-explanation-v1",
            "positive_reasons": ["matches current memory"],
            "suppression_reasons": reasons,
        },
    }


def _verified_report(run_id: uuid.UUID) -> dict[str, Any]:
    return {
        "result_mode": "research_report",
        "contract_version": "research-report-v1",
        "run_id": str(run_id),
        "report_status": "verified",
        "verified_claims": [
            {
                "claim": "Fresh Warm Novel is warm and character-driven.",
                "evidence_ids": [str(uuid.uuid4())],
                "reason_codes": ["supported_by_medium_quality_evidence"],
            }
        ],
        "uncertain_claims": [],
        "rejected_claims": [],
    }


async def _run_orchestration_verification() -> None:
    user_id = uuid.uuid4()
    thread_id = uuid.uuid4()
    run_id = uuid.uuid4()

    await _insert_temp_user_and_thread(user_id, thread_id)
    try:
        remembered = await get_memory_orchestrator().remember_candidate(
            MemoryCandidate(
                type="preference",
                subject="mood",
                value="quiet",
                polarity="like",
                source_text="I like quiet books.",
                source_kind="user_message",
                user_id=user_id,
                thread_id=thread_id,
            )
        )
        _assert(remembered.decision.decision == "allow", str(remembered))

        memory_before = await _table_count("memory_events", user_id)
        recommendation_before = await _table_count("recommendation_events", user_id)
        research_runs_before = await _table_count("research_runs", user_id)
        evidence_before = await _evidence_count(user_id)

        reset_tool_admission_gate()
        with request_id_scope("verify-book-turn-ordinary-route"):
            with user_message_scope("Please recommend warm character-driven books."):
                ordinary = await _plan_turn(
                    user_id=str(user_id),
                    query="warm character-driven books",
                )
        _assert(ordinary["result_mode"] == "book_turn_orchestration", str(ordinary))
        _assert(
            ordinary["contract_version"] == "book-turn-orchestration-v1",
            str(ordinary),
        )
        _assert(ordinary["route"] == "ordinary_recommendation", str(ordinary))
        _assert("search_books" in ordinary["recommended_next_tools"], str(ordinary))
        _assert(ordinary["policy"]["can_search_books"] is True, str(ordinary["policy"]))
        _assert(
            ordinary["personalization_constraints"]["metadata"]["constraint_source"]
            == "current_memory",
            str(ordinary["personalization_constraints"]),
        )
        _assert(
            ordinary["metadata"]["tool_admission"]["metadata"]["declaration"][
                "side_effect_scope"
            ]
            == "none",
            str(ordinary["metadata"]["tool_admission"]),
        )

        reset_tool_admission_gate()
        with request_id_scope("verify-book-turn-history-route"):
            with user_message_scope("为什么没推荐 Example Novel？"):
                history = await _plan_turn(
                    user_id=str(user_id),
                    query="为什么没推荐 Example Novel？",
                    book_title="Example Novel",
                )
        _assert(history["route"] == "recommendation_history", str(history))
        _assert(history["history_mode"] == "suppression_explanation", str(history))
        _assert(
            history["recommended_next_tools"] == ["get_recommendation_history"],
            str(history),
        )
        _assert("search_books" in history["policy"]["denied_tools"], str(history))
        _assert(
            any(
                step["name"] == "search_books"
                and step["status"] == "blocked_by_route"
                for step in history["route_steps"]
            ),
            str(history["route_steps"]),
        )

        reset_tool_admission_gate()
        with request_id_scope("verify-book-turn-researched-needs-candidates"):
            with user_message_scope(
                "Please deep research and recommend warm character-driven books."
            ):
                researched_needs_candidates = await _plan_turn(
                    user_id=str(user_id),
                    query="warm character-driven books",
                )
        _assert(
            researched_needs_candidates["route"] == "researched_recommendation",
            str(researched_needs_candidates),
        )
        _assert(
            researched_needs_candidates["recommended_next_tools"][:2]
            == ["search_books", "plan_recommendation_research_workflow"],
            str(researched_needs_candidates),
        )
        workflow = researched_needs_candidates["recommendation_research_workflow"]
        _assert(workflow["status"] == "needs_candidates", str(workflow))
        _assert(workflow["result_mode"] == "recommendation_research_workflow", str(workflow))

        reset_tool_admission_gate()
        with request_id_scope("verify-book-turn-researched-ready"):
            with user_message_scope(
                "Please deep research and recommend warm character-driven books."
            ):
                researched_ready = await _plan_turn(
                    user_id=str(user_id),
                    query="warm character-driven books",
                    candidates=[_candidate("Fresh Warm Novel")],
                    research_report=_verified_report(run_id),
                )
        _assert(researched_ready["route"] == "researched_recommendation", str(researched_ready))
        ready_workflow = researched_ready["recommendation_research_workflow"]
        _assert(ready_workflow["ready_to_fuse"] is True, str(ready_workflow))
        _assert(
            researched_ready["recommended_next_tools"]
            == ["build_recommendation_research_report"],
            str(researched_ready),
        )

        reset_tool_admission_gate()
        with request_id_scope("verify-book-turn-deep-research-route"):
            with user_message_scope("Please deep research Nonviolent Communication."):
                deep = await _plan_turn(
                    user_id=str(user_id),
                    query="Nonviolent Communication",
                )
        _assert(deep["route"] == "deep_research", str(deep))
        _assert("start_research" in deep["recommended_next_tools"], str(deep))
        _assert(deep["recommendation_research_workflow"] is None, str(deep))

        reset_tool_admission_gate()
        with request_id_scope("verify-book-turn-answer-route"):
            with user_message_scope("What is the style of Nonviolent Communication?"):
                answer = await _plan_turn(
                    user_id=str(user_id),
                    query="What is the style of Nonviolent Communication?",
                )
        _assert(answer["route"] == "answer_question", str(answer))
        _assert("search_books" in answer["policy"]["denied_tools"], str(answer))
        _assert(answer["recommended_next_tools"] == [], str(answer))

        _assert(
            await _table_count("memory_events", user_id) == memory_before,
            "turn orchestration should not write memory",
        )
        _assert(
            await _table_count("recommendation_events", user_id)
            == recommendation_before,
            "turn orchestration should not write recommendation events",
        )
        _assert(
            await _table_count("research_runs", user_id) == research_runs_before,
            "turn orchestration should not create research runs",
        )
        _assert(
            await _evidence_count(user_id) == evidence_before,
            "turn orchestration should not write evidence",
        )
    finally:
        await _delete_temp_user(user_id)
        reset_tool_admission_gate()


async def _main(skip_migration: bool) -> None:
    load_dotenv()
    if not skip_migration:
        _init_postgres()
    init_embedding_model()
    await init_database()
    try:
        await _run_orchestration_verification()
    finally:
        await dispose_database()
    print("book turn orchestration verification passed")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-migration", action="store_true")
    args = parser.parse_args()

    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(_main(skip_migration=args.skip_migration))


if __name__ == "__main__":
    main()
