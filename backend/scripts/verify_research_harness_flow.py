"""
Verify the Phase E LangGraph ResearchHarnessRuntime.

This check uses deterministic input observations instead of live web providers.
It verifies graph execution, step field confirmation, Postgres-backed resume,
and that research evidence does not create long-term memory.

Usage:
    cd backend
    .\\.venv\\Scripts\\python.exe scripts\\verify_research_harness_flow.py
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import uuid
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import text

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.infra.database import dispose_database, get_database, init_database
from app.infra.llm.embedding import init_embedding_model
from app.services.research import ResearchEvidence, get_research_orchestrator
from app.services.research.harness import (
    ResearchHarnessInput,
    ResearchHarnessRuntime,
    ResearchObservation,
)
from app.services.research.harness.contracts import (
    HarnessFieldError,
    confirm_next_step_fields,
    require_next_step_ready,
)
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
            {"user_id": user_id, "display_name": "Research Harness Verify"},
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
                "title": "Research Harness Verify",
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


def _assert_field_guard_blocks_missing_fields() -> None:
    confirmation = confirm_next_step_fields(
        {"run_id": uuid.uuid4()},
        current_step="planner",
        next_step="search_task_builder",
    )
    _assert(not confirmation.ready, "missing plan fields should not be ready")
    _assert(
        "plan.objective" in confirmation.missing_fields,
        "missing plan objective should be reported",
    )
    try:
        require_next_step_ready(
            {
                "run_id": uuid.uuid4(),
                "field_confirmation": confirmation,
                "field_confirmations": [confirmation],
            },
            next_step="search_task_builder",
        )
    except HarnessFieldError:
        return
    raise AssertionError("next node should not start with missing required fields")


def _confirmation_pairs(result) -> list[tuple[str, str]]:
    return [
        (item.current_step, item.next_step)
        for item in result.field_confirmations
    ]


async def _run_full_harness_flow(
    user_id: uuid.UUID,
    thread_id: uuid.UUID,
) -> None:
    runtime = ResearchHarnessRuntime()
    before_memory_count = await _memory_event_count(user_id)
    result = await runtime.run(
        ResearchHarnessInput(
            user_id=user_id,
            thread_id=thread_id,
            objective=(
                "Find one warm, character-driven novel candidate for a reader "
                "who avoids bloody or very dark content."
            ),
            subquestions=[
                "Which candidate is warm, character-driven, and not bloody?",
            ],
            gaps=["Need at least one source-backed candidate claim."],
            next_actions=["Search for a source-backed candidate claim."],
            budget={"max_steps": 7, "max_sources": 2},
            stop_criteria=["At least one claim has an evidence id."],
            observations=[
                ResearchObservation(
                    source_type="web",
                    source_title="Example Review",
                    source_url="https://example.test/warm-novel-review",
                    claim=(
                        "Example Novel is described as warm and "
                        "character-driven without bloody content."
                    ),
                    excerpt=(
                        "The review emphasizes relationships, warmth, and "
                        "low-violence stakes."
                    ),
                    quality="medium",
                    relevance=5,
                    metadata={"provider_source": "phase_e_verify"},
                )
            ],
            metadata={"trace_id": "phase_e_full_harness"},
        )
    )

    _assert(result.status == "completed", "harness run should complete")
    _assert(
        result.finalization.verified_claims,
        "final answer should be built from verified claims",
    )
    _assert(
        result.finalization.verified_claims[0].evidence_ids,
        "verified claim should reference evidence ids",
    )
    _assert(
        "Example Novel is described as warm" in result.finalization.final_answer,
        "final answer should include the admitted verified claim",
    )
    pairs = _confirmation_pairs(result)
    expected_pairs = [
        ("planner", "search_task_builder"),
        ("search_task_builder", "source_visitor"),
        ("source_visitor", "aggregator"),
        ("aggregator", "gap_filler"),
        ("gap_filler", "verifier"),
        ("verifier", "finalizer"),
        ("finalizer", "end"),
    ]
    _assert(pairs == expected_pairs, "every graph transition should be confirmed")
    _assert(
        all(item.ready for item in result.field_confirmations),
        "all full-run field confirmations should be ready",
    )
    _assert(
        result.resume_state is not None and result.resume_state.evidence_count == 1,
        "result should include Postgres-reconstructed resume state",
    )
    _assert(
        result.research_state.state.status == "completed",
        "final research state should be completed",
    )
    after_memory_count = await _memory_event_count(user_id)
    _assert(
        before_memory_count == after_memory_count == 0,
        "harness evidence must not write long-term memory",
    )

    resumed = await runtime.resume_from_postgres(
        user_id=user_id,
        run_id=result.run_id,
    )
    _assert(
        resumed.status == "completed",
        "resume snapshot should be reconstructed from completed Postgres state",
    )
    _assert(
        resumed.evidence_count == 1,
        "resume snapshot should include persisted evidence count",
    )


async def _run_resume_and_finalize_flow(
    user_id: uuid.UUID,
    thread_id: uuid.UUID,
) -> None:
    orchestrator = get_research_orchestrator()
    started = await orchestrator.start_research(
        user_id=user_id,
        thread_id=thread_id,
        objective="Resume from Postgres and finalize one supported claim.",
        subquestions=["Which claim has stored evidence?"],
        gaps=["Need verifier admission."],
        next_actions=["Add evidence before finalization."],
        budget={"max_steps": 4},
        stop_criteria=["One evidence-backed claim is admitted."],
        metadata={"trace_id": "phase_e_resume_setup"},
    )
    run_id = started.run.id
    _assert(run_id is not None, "manual run should return an id")
    await orchestrator.search_research(
        user_id=user_id,
        run_id=run_id,
        query="resume supported claim",
        status="completed",
        rationale="Prepare a persisted search step before simulated context loss.",
        results=[
            {
                "title": "Resume Source",
                "url": "https://example.test/resume-source",
            }
        ],
    )
    await orchestrator.visit_source(
        user_id=user_id,
        run_id=run_id,
        url="https://example.test/resume-source",
        title="Resume Source",
        summary="The source backs one deterministic claim.",
    )
    evidence = ResearchEvidence(
        run_id=run_id,
        source_type="web",
        source_title="Resume Source",
        source_url="https://example.test/resume-source",
        claim="Resume Claim is supported by persisted evidence.",
        excerpt="A persisted source-backed claim for resume verification.",
        quality="medium",
        relevance=5,
        metadata={"provider_source": "phase_e_resume_verify"},
    )
    evidenced = await orchestrator.add_evidence(
        user_id=user_id,
        run_id=run_id,
        evidence=evidence,
        known_facts=["Resume Claim is supported by persisted evidence."],
        gaps=[],
        next_actions=["Resume with a fresh harness runtime and finalize."],
    )
    _assert(
        len(evidenced.evidence) == 1,
        "manual setup should persist one evidence item",
    )
    await orchestrator.update_research_state(
        user_id=user_id,
        run_id=run_id,
        gaps=[],
        next_actions=["Resume with a fresh harness runtime and finalize."],
        metadata={"harness": {"node": "manual_resume_setup"}},
        replace=True,
    )

    runtime_after_context_loss = ResearchHarnessRuntime()
    result = await runtime_after_context_loss.resume_and_finalize(
        user_id=user_id,
        run_id=run_id,
    )
    _assert(
        result.resumed_from_postgres,
        "resume_and_finalize should mark the result as resumed",
    )
    _assert(
        result.status == "completed",
        "resumed harness should complete the active run",
    )
    _assert(
        result.field_confirmations[0].current_step == "gap_filler",
        "resumed flow should begin by confirming verifier fields",
    )
    _assert(
        "Resume Claim is supported" in result.finalization.final_answer,
        "resumed final answer should use persisted evidence",
    )


async def _run_research_harness_flow() -> None:
    _assert_field_guard_blocks_missing_fields()
    full_user_id = uuid.uuid4()
    full_thread_id = uuid.uuid4()
    resume_user_id = uuid.uuid4()
    resume_thread_id = uuid.uuid4()

    await _insert_temp_user_and_thread(full_user_id, full_thread_id)
    await _insert_temp_user_and_thread(resume_user_id, resume_thread_id)
    try:
        await _run_full_harness_flow(full_user_id, full_thread_id)
        await _run_resume_and_finalize_flow(resume_user_id, resume_thread_id)
        print("research harness verification passed")
        print(f"full_user_id={full_user_id}")
        print(f"full_thread_id={full_thread_id}")
        print(f"resume_user_id={resume_user_id}")
        print(f"resume_thread_id={resume_thread_id}")
    finally:
        await _delete_temp_user(full_user_id)
        await _delete_temp_user(resume_user_id)


async def _main(skip_migration: bool) -> None:
    load_dotenv()
    if not skip_migration:
        _init_postgres()
    init_embedding_model()
    await init_database()
    try:
        await _run_research_harness_flow()
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
