"""Verify researched recommendation workflow planning.

This check avoids live web/LLM calls. It verifies:
- plan_recommendation_research_workflow is gated by Deep Search / Deep Research intent
- the planner reports missing candidates, missing research, missing report, and
  ready-to-fuse states from app-owned payloads
- CurrentMemory-derived personalization constraints are included read-only
- the planner writes no memory, recommendation events, research runs, or evidence
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

from app.agents.tools import research as research_tools
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
            {"user_id": user_id, "display_name": "Recommendation Workflow Verify"},
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
                "title": "Recommendation Workflow Verify",
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


async def _plan_workflow(**payload: Any) -> dict[str, Any]:
    return json.loads(
        await research_tools.plan_recommendation_research_workflow.ainvoke(payload)
    )


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


async def _run_workflow_verification() -> None:
    user_id = uuid.uuid4()
    thread_id = uuid.uuid4()
    run_id = uuid.uuid4()

    await _insert_temp_user_and_thread(user_id, thread_id)
    try:
        reset_tool_admission_gate()
        with request_id_scope("verify-research-workflow-blocked"):
            with user_message_scope("Please recommend warm books."):
                blocked = await _plan_workflow(
                    user_id=str(user_id),
                    query="warm books",
                )
        _assert(blocked["status"] == "tool_blocked", str(blocked))
        _assert(
            blocked["result_mode"] == "recommendation_research_workflow",
            str(blocked),
        )
        _assert(
            "can_use_research_tools"
            in blocked["metadata"]["tool_admission"]["metadata"][
                "missing_policy_flags"
            ],
            str(blocked["metadata"]["tool_admission"]),
        )

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
        with request_id_scope("verify-research-workflow-planning"):
            with user_message_scope(
                "Please deep research and recommend warm character-driven books."
            ):
                needs_candidates = await _plan_workflow(
                    user_id=str(user_id),
                    query="warm books",
                )
                needs_research = await _plan_workflow(
                    user_id=str(user_id),
                    query="warm books",
                    candidates=[_candidate("Fresh Warm Novel")],
                )
                needs_report = await _plan_workflow(
                    user_id=str(user_id),
                    query="warm books",
                    candidates=[_candidate("Fresh Warm Novel")],
                    research_state={"run": {"id": str(run_id)}},
                )
                needs_verified = await _plan_workflow(
                    user_id=str(user_id),
                    query="warm books",
                    candidates=[_candidate("Fresh Warm Novel")],
                    research_report={
                        "result_mode": "research_report",
                        "contract_version": "research-report-v1",
                        "run_id": str(run_id),
                        "report_status": "needs_more_research",
                        "verified_claims": [],
                    },
                )
                ready = await _plan_workflow(
                    user_id=str(user_id),
                    query="warm books",
                    candidates=[_candidate("Fresh Warm Novel")],
                    research_report=_verified_report(run_id),
                )
                suppressed_only = await _plan_workflow(
                    user_id=str(user_id),
                    query="warm books",
                    candidates=[_candidate("Already Read Novel", suppressed=True)],
                    research_report=_verified_report(run_id),
                )

        _assert(needs_candidates["status"] == "needs_candidates", str(needs_candidates))
        _assert(
            needs_candidates["recommended_next_tools"][0] == "search_books",
            str(needs_candidates),
        )
        constraints = needs_candidates["personalization_constraints"]
        _assert(constraints is not None, str(needs_candidates))
        _assert("quiet" in constraints["preferred_terms"], str(constraints))
        _assert(
            constraints["metadata"]["constraint_source"] == "current_memory",
            str(constraints),
        )

        _assert(needs_research["status"] == "needs_research", str(needs_research))
        _assert(
            "start_research" in needs_research["recommended_next_tools"],
            str(needs_research),
        )
        _assert(needs_report["status"] == "needs_research_report", str(needs_report))
        _assert(
            needs_report["recommended_next_tools"] == ["build_research_report"],
            str(needs_report),
        )
        _assert(
            needs_verified["status"] == "needs_verified_research",
            str(needs_verified),
        )
        _assert(ready["status"] == "ready_to_fuse", str(ready))
        _assert(ready["ready_to_fuse"] is True, str(ready))
        _assert(
            ready["recommended_next_tools"] == ["build_recommendation_research_report"],
            str(ready),
        )
        _assert(ready["verified_claim_count"] == 1, str(ready))
        _assert(suppressed_only["status"] == "needs_candidates", str(suppressed_only))
        _assert(suppressed_only["suppressed_candidate_count"] == 1, str(suppressed_only))
        _assert(suppressed_only["ready_to_fuse"] is False, str(suppressed_only))
        _assert(ready["metadata"]["external_call"] is False, str(ready["metadata"]))
        _assert(
            ready["metadata"]["writes_long_term_memory"] is False,
            str(ready["metadata"]),
        )
        _assert(
            ready["metadata"]["writes_recommendation_events"] is False,
            str(ready["metadata"]),
        )
        _assert(
            ready["metadata"]["writes_research_state"] is False,
            str(ready["metadata"]),
        )
        _assert(ready["metadata"]["writes_evidence"] is False, str(ready["metadata"]))

        _assert(
            await _table_count("memory_events", user_id) == memory_before,
            "planner should not write memory",
        )
        _assert(
            await _table_count("recommendation_events", user_id)
            == recommendation_before,
            "planner should not write recommendation events",
        )
        _assert(
            await _table_count("research_runs", user_id) == research_runs_before,
            "planner should not create research runs",
        )
        _assert(
            await _evidence_count(user_id) == evidence_before,
            "planner should not write evidence",
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
        await _run_workflow_verification()
    finally:
        await dispose_database()
    print("recommendation research workflow verification passed")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-migration", action="store_true")
    args = parser.parse_args()

    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(_main(skip_migration=args.skip_migration))


if __name__ == "__main__":
    main()
