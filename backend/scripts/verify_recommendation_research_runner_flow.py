"""Verify bounded researched recommendation workflow runner.

This check avoids live web/LLM calls. It verifies:
- run_recommendation_research_workflow is gated by Deep Search / Deep Research intent
- existing candidates + verified research-report-v1 fuse without writing research state
- existing candidates + source-backed observations run the local harness and fuse
- the runner writes no long-term memory or recommendation events
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


VERIFIED_CLAIM = "Fresh Warm Novel is warm and character-driven."


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
            {"user_id": user_id, "display_name": "Recommendation Runner Verify"},
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
                "title": "Recommendation Runner Verify",
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


async def _run_workflow(**payload: Any) -> dict[str, Any]:
    return json.loads(
        await research_tools.run_recommendation_research_workflow.ainvoke(payload)
    )


def _candidate(*, suppressed: bool = False) -> dict[str, Any]:
    return {
        "id": str(uuid.uuid4()),
        "title": "Fresh Warm Novel",
        "authors": ["Example Author"],
        "summary": "A warm, quiet, character-driven novel.",
        "recommendation": {
            "score": 1.5,
            "suppressed": suppressed,
            "positive_reasons": ["matches current memory"],
            "suppression_reasons": ["already_read"] if suppressed else [],
        },
        "recommendation_explanation": {
            "contract_version": "recommendation-explanation-v1",
            "positive_reasons": ["matches current memory"],
            "suppression_reasons": ["already_read"] if suppressed else [],
        },
    }


def _verified_report(run_id: uuid.UUID) -> dict[str, Any]:
    return {
        "result_mode": "research_report",
        "contract_version": "research-report-v1",
        "run_id": str(run_id),
        "user_id": str(uuid.uuid4()),
        "objective": "Research warm recommendation candidates.",
        "run_status": "completed",
        "report_status": "verified",
        "verified_claims": [
            {
                "claim": VERIFIED_CLAIM,
                "status": "admitted",
                "evidence_ids": [str(uuid.uuid4())],
                "evidence": [],
                "quality": "medium",
                "reason_codes": ["supported_by_evidence"],
                "explanation": "Candidate claim has sufficient supporting evidence.",
                "metadata": {},
            }
        ],
        "uncertain_claims": [],
        "rejected_claims": [],
        "sources": [
            {
                "evidence_id": str(uuid.uuid4()),
                "source_type": "web",
                "source_title": "Reliable Review",
                "source_url": "https://example.test/fresh-warm-review",
                "quality": "medium",
                "relevance": 5,
                "claim": VERIFIED_CLAIM,
            }
        ],
        "gaps": [],
        "conflicts": [],
        "exhausted_queries": [],
        "next_actions": [],
        "memory_context": {"memory_ids": [], "constraints": []},
        "verification": {
            "run_id": str(run_id),
            "decisions": [],
            "admitted_claims": [],
            "uncertain_claims": [],
            "rejected_claims": [],
            "blocking_gaps": [],
            "conflicts": [],
            "ready_for_final_answer": True,
            "can_finalize_with_uncertainty": False,
            "metadata": {},
        },
        "metadata": {},
    }


def _observation() -> dict[str, Any]:
    return {
        "source_type": "web",
        "source_title": "Reliable Review",
        "source_url": "https://example.test/fresh-warm-review",
        "claim": VERIFIED_CLAIM,
        "excerpt": "The review describes Fresh Warm Novel as warm and character-driven.",
        "quality": "medium",
        "relevance": 5,
        "metadata": {
            "provider_source": "recommendation_runner_verify",
            "provider_raw": {"fixture": "runner"},
        },
    }


async def _run_runner_verification() -> None:
    user_id = uuid.uuid4()
    thread_id = uuid.uuid4()

    await _insert_temp_user_and_thread(user_id, thread_id)
    try:
        reset_tool_admission_gate()
        with request_id_scope("verify-recommendation-runner-blocked"):
            with user_message_scope("Please recommend warm books."):
                blocked = await _run_workflow(
                    user_id=str(user_id),
                    query="warm books",
                    candidates=[_candidate()],
                    research_report=_verified_report(uuid.uuid4()),
                )
        _assert(blocked["status"] == "tool_blocked", str(blocked))
        _assert(blocked["result_mode"] == "recommendation_research_runner", str(blocked))
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
        research_before = await _table_count("research_runs", user_id)
        evidence_before = await _evidence_count(user_id)

        reset_tool_admission_gate()
        with request_id_scope("verify-recommendation-runner-existing-report"):
            with user_message_scope(
                "Please deep research and recommend warm character-driven books."
            ):
                direct = await _run_workflow(
                    user_id=str(user_id),
                    thread_id=str(thread_id),
                    query="warm character-driven books",
                    candidates=[_candidate()],
                    research_report=_verified_report(uuid.uuid4()),
                    allow_runtime=True,
                )
        _assert(direct["status"] == "fused", str(direct))
        _assert(direct["runtime"] is None, str(direct))
        _assert(direct["workflow_before"]["ready_to_fuse"] is True, str(direct))
        _assert(direct["workflow_after"]["ready_to_fuse"] is True, str(direct))
        _assert(
            direct["recommendation_report"]["result_mode"]
            == "recommendation_research_report",
            str(direct),
        )
        _assert(
            direct["metadata"]["writes_research_state"] is False,
            str(direct["metadata"]),
        )
        _assert(await _table_count("research_runs", user_id) == research_before, str(direct))
        _assert(await _evidence_count(user_id) == evidence_before, str(direct))

        reset_tool_admission_gate()
        with request_id_scope("verify-recommendation-runner-local-runtime"):
            with user_message_scope(
                "Please deep research and recommend warm character-driven books."
            ):
                runtime = await _run_workflow(
                    user_id=str(user_id),
                    thread_id=str(thread_id),
                    query="warm character-driven books",
                    candidates=[_candidate()],
                    observations=[_observation()],
                    subquestions=["Is Fresh Warm Novel warm and character-driven?"],
                    gaps=["Need source-backed evidence."],
                    next_actions=["Run local harness."],
                    budget={"required_evidence_quality": "medium"},
                    stop_criteria=["One medium-quality claim is admitted."],
                )
        _assert(runtime["status"] == "fused", str(runtime))
        _assert(runtime["runtime"]["result_mode"] == "research_runtime", str(runtime))
        _assert(runtime["research_report"]["result_mode"] == "research_report", str(runtime))
        _assert(
            runtime["recommendation_report"]["recommended_candidates"],
            str(runtime["recommendation_report"]),
        )
        _assert(runtime["workflow_before"]["ready_to_fuse"] is False, str(runtime))
        _assert(runtime["workflow_after"]["ready_to_fuse"] is True, str(runtime))
        _assert(runtime["metadata"]["runtime_executed"] is True, str(runtime["metadata"]))
        _assert(runtime["metadata"]["writes_research_state"] is True, str(runtime["metadata"]))
        _assert(runtime["metadata"]["writes_evidence"] is True, str(runtime["metadata"]))
        _assert(
            await _table_count("research_runs", user_id) == research_before + 1,
            "runner should create exactly one research run for supplied observations",
        )
        _assert(
            await _evidence_count(user_id) == evidence_before + 1,
            "runner should admit exactly one evidence row for supplied observation",
        )
        _assert(
            await _table_count("memory_events", user_id) == memory_before,
            "runner should not write memory",
        )
        _assert(
            await _table_count("recommendation_events", user_id)
            == recommendation_before,
            "runner should not write recommendation events",
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
        await _run_runner_verification()
    finally:
        await dispose_database()
    print("recommendation research runner verification passed")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-migration", action="store_true")
    args = parser.parse_args()

    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(_main(skip_migration=args.skip_migration))


if __name__ == "__main__":
    main()
