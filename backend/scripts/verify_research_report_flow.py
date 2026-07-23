"""Verify read-only Deep Research report projection.

This check avoids live web/LLM calls. It verifies:
- build_research_report returns source-backed verified and uncertain claims
- report projection includes current memory constraints without writing memory
- report projection does not mutate research state
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import uuid
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import text

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.agents.tools import research as research_tools
from app.infra.database import dispose_database, get_database, init_database
from app.infra.llm.embedding import init_embedding_model
from app.services.memory import MemoryCandidate, get_memory_orchestrator
from app.services.research import ResearchEvidence, get_research_orchestrator
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
            {"user_id": user_id, "display_name": "Research Report Verify"},
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
                "title": "Research Report Verify",
            },
        )


async def _delete_temp_user(user_id: uuid.UUID) -> None:
    db = get_database()
    async with db.session() as session:
        await session.execute(
            text("DELETE FROM public.users WHERE id = :user_id"),
            {"user_id": user_id},
        )


async def _memory_event_count(user_id: uuid.UUID) -> int:
    db = get_database()
    async with db.session() as session:
        count = await session.scalar(
            text("SELECT COUNT(*) FROM public.memory_events WHERE user_id = :user_id"),
            {"user_id": user_id},
        )
        return int(count or 0)


async def _research_step_count(run_id: uuid.UUID) -> int:
    db = get_database()
    async with db.session() as session:
        count = await session.scalar(
            text("SELECT COUNT(*) FROM public.research_steps WHERE run_id = :run_id"),
            {"run_id": run_id},
        )
        return int(count or 0)


async def _run_research_report_flow() -> None:
    user_id = uuid.uuid4()
    thread_id = uuid.uuid4()
    memory = get_memory_orchestrator()
    research = get_research_orchestrator()

    await _insert_temp_user_and_thread(user_id, thread_id)
    try:
        remembered = await memory.remember_candidate(
            MemoryCandidate(
                user_id=user_id,
                thread_id=thread_id,
                type="preference",
                subject="content",
                value="avoid bleak or overly dark books",
                polarity="avoid",
                source_kind="user_message",
                source_text="I avoid bleak or overly dark books.",
            )
        )
        _assert(remembered.memory is not None, "memory setup should be admitted")

        started = await research.start_research(
            user_id=user_id,
            thread_id=thread_id,
            objective="Assess whether Example Novel fits a warm reading request.",
            mode="deep_research",
            subquestions=["Is Example Novel warm and character-driven?"],
            gaps=[],
            next_actions=["Collect source-backed evidence."],
            budget={"required_evidence_quality": "medium"},
            stop_criteria=["At least one claim has medium quality evidence."],
        )
        run_id = started.run.id
        _assert(run_id is not None, "run id should exist")
        assert run_id is not None

        with_verified = await research.add_evidence(
            user_id=user_id,
            run_id=run_id,
            evidence=ResearchEvidence(
                run_id=run_id,
                source_type="web",
                source_title="Reliable Review",
                source_url="https://example.test/reliable-review",
                claim="Example Novel is warm and character-driven.",
                excerpt="The review describes a gentle character-focused story.",
                quality="medium",
                relevance=5,
            ),
            known_facts=["Example Novel is warm and character-driven."],
            next_actions=["Check content risk."],
        )
        await research.add_evidence(
            user_id=user_id,
            run_id=run_id,
            evidence=ResearchEvidence(
                run_id=run_id,
                source_type="web",
                source_title="Weak Forum Note",
                source_url="https://example.test/weak-forum-note",
                claim="Example Novel may have no bleak content.",
                excerpt="A weak user note says it is not bleak.",
                quality="low",
                relevance=3,
            ),
            known_facts=["Weak note suggests no bleak content."],
            next_actions=["Build report with uncertainty labels."],
        )
        _assert(len(with_verified.evidence) >= 1, "verified evidence should be stored")

        memory_count_before = await _memory_event_count(user_id)
        step_count_before = await _research_step_count(run_id)
        with request_id_scope("verify-research-report"):
            with user_message_scope("Please deep research and give me a research report."):
                report = json.loads(
                    await research_tools.build_research_report.ainvoke(
                        {
                            "user_id": str(user_id),
                            "run_id": str(run_id),
                            "limit_steps": 100,
                            "limit_evidence": 100,
                        }
                    )
                )

        _assert(report["result_mode"] == "research_report", str(report))
        _assert(report["contract_version"] == "research-report-v1", str(report))
        _assert(report["report_status"] == "verified", str(report))
        _assert(
            report["verification"]["ready_for_final_answer"],
            str(report["verification"]),
        )
        _assert(
            [claim["claim"] for claim in report["verified_claims"]]
            == ["Example Novel is warm and character-driven."],
            str(report["verified_claims"]),
        )
        _assert(
            report["uncertain_claims"]
            and report["uncertain_claims"][0]["claim"]
            == "Example Novel may have no bleak content.",
            str(report["uncertain_claims"]),
        )
        _assert(
            any(source["source_title"] == "Reliable Review" for source in report["sources"]),
            str(report["sources"]),
        )
        _assert(
            "avoid bleak or overly dark books"
            in " ".join(report["memory_context"]["constraints"]),
            str(report["memory_context"]),
        )
        _assert(
            await _memory_event_count(user_id) == memory_count_before,
            "report projection should not write memory",
        )
        _assert(
            await _research_step_count(run_id) == step_count_before,
            "report projection should not write research steps",
        )
    finally:
        await _delete_temp_user(user_id)


async def _main(skip_migration: bool) -> None:
    load_dotenv()
    if not skip_migration:
        _init_postgres()
    init_embedding_model()
    await init_database()
    try:
        await _run_research_report_flow()
    finally:
        await dispose_database()
    print("research report verification passed")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-migration", action="store_true")
    args = parser.parse_args()

    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(_main(skip_migration=args.skip_migration))


if __name__ == "__main__":
    main()
