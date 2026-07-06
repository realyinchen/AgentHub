"""
Verify the Phase G observation provider adapters.

This check verifies provider status mapping, provider metadata normalization,
Harness source-provider integration, structured provider failure recording, and
that provider observations do not write long-term memory.

Usage:
    cd backend
    .\\.venv\\Scripts\\python.exe scripts\\verify_research_observation_provider_flow.py
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import uuid
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from sqlalchemy import text

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.infra.database import dispose_database, get_database, init_database
from app.infra.llm.embedding import init_embedding_model
from app.services.research import get_research_orchestrator
from app.services.research.harness import ResearchHarnessInput, ResearchHarnessRuntime
from app.services.research.harness.contracts import HarnessFieldError
from app.services.research.observation_providers import (
    ObservationProviderRequest,
    ResearchObservation,
    SourceObservationProvider,
    map_provider_status,
)
from scripts.init_database import _init_postgres


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


async def _insert_temp_user_and_thread(
    user_id: uuid.UUID,
    thread_id: uuid.UUID,
    title: str,
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
            {"user_id": user_id, "display_name": title},
        )
        await session.execute(
            text(
                """
                INSERT INTO public.conversations (thread_id, user_id, title)
                VALUES (:thread_id, :user_id, :title)
                ON CONFLICT (thread_id) DO NOTHING
                """
            ),
            {"thread_id": thread_id, "user_id": user_id, "title": title},
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


def _search_steps(result: dict[str, Any]) -> list[dict[str, Any]]:
    return [step for step in result["steps"] if step["step_type"] == "search"]


async def _run_direct_provider_checks() -> None:
    _assert(map_provider_status("ok") == "completed", "ok should map to completed")
    _assert(
        map_provider_status("empty") == "empty_result",
        "empty should map to empty_result",
    )
    _assert(map_provider_status("timeout") == "timeout", "timeout should map")
    _assert(
        map_provider_status("rate_limited") == "failed",
        "provider-specific failure should map to failed",
    )

    provider = SourceObservationProvider(provider_name="phase_g_source")
    result = await provider.observe(
        ObservationProviderRequest(
            run_id=uuid.uuid4(),
            query="warm character-driven novels",
            subquestion="Find one source-backed candidate.",
            seed_observations=[
                ResearchObservation(
                    source_type="web",
                    source_title="Provider Source",
                    source_url="https://example.test/provider-source",
                    claim="Provider Candidate is warm and character-driven.",
                    excerpt="The source focuses on relationships and warmth.",
                    quality="medium",
                    relevance=5,
                )
            ],
            metadata={"trace_id": "phase_g_direct_provider"},
        )
    )
    _assert(result.status == "completed", "seed observation should complete")
    observation = result.observations[0]
    _assert(
        observation.metadata["provider_source"] == "phase_g_source",
        "provider_source should be normalized",
    )
    _assert(
        isinstance(observation.metadata["provider_raw"], dict),
        "provider_raw should preserve raw provider payload",
    )

    failed = await provider.observe(
        ObservationProviderRequest(
            run_id=uuid.uuid4(),
            query="forced timeout",
            metadata={
                "provider": {
                    "force_status": "timeout",
                    "error": "simulated provider timeout",
                }
            },
        )
    )
    _assert(failed.status == "timeout", "forced timeout should map to timeout")
    _assert(failed.error == "simulated provider timeout", "error should be preserved")
    _assert(failed.observations == [], "failed provider result should not emit observations")


async def _run_harness_provider_success() -> None:
    user_id = uuid.uuid4()
    thread_id = uuid.uuid4()
    await _insert_temp_user_and_thread(user_id, thread_id, "Observation Provider Success")
    try:
        before_memory_count = await _memory_event_count(user_id)
        runtime = ResearchHarnessRuntime(
            observation_provider=SourceObservationProvider("phase_g_source")
        )
        result = await runtime.run(
            ResearchHarnessInput(
                user_id=user_id,
                thread_id=thread_id,
                objective="Verify provider observation mapping into research evidence.",
                subquestions=["Which provider claim is source-backed?"],
                next_actions=["Ask provider for a normalized observation."],
                budget={"max_sources": 2},
                stop_criteria=["One provider claim is admitted."],
                observations=[
                    ResearchObservation(
                        source_type="web",
                        source_title="Provider Harness Source",
                        source_url="https://example.test/provider-harness-source",
                        claim="Provider Harness Candidate is source-backed.",
                        excerpt="The provider result contains a concise source excerpt.",
                        quality="medium",
                        relevance=5,
                    )
                ],
                metadata={"trace_id": "phase_g_harness_success"},
            )
        )
        _assert(result.status == "completed", "provider-backed harness run should complete")
        _assert(len(result.research_state.evidence) == 1, "evidence should be stored")
        evidence = result.research_state.evidence[0]
        _assert(
            evidence.metadata["provider_source"] == "phase_g_source",
            "evidence should keep provider_source metadata",
        )
        _assert(
            isinstance(evidence.metadata["provider_raw"], dict),
            "evidence should keep provider_raw metadata",
        )
        steps = _search_steps(result.research_state.model_dump(mode="json"))
        _assert(steps[-1]["status"] == "completed", "search step should record provider status")
        after_memory_count = await _memory_event_count(user_id)
        _assert(
            before_memory_count == after_memory_count == 0,
            "provider observations must not write long-term memory",
        )
    finally:
        await _delete_temp_user(user_id)


async def _run_harness_provider_failure() -> None:
    user_id = uuid.uuid4()
    thread_id = uuid.uuid4()
    await _insert_temp_user_and_thread(user_id, thread_id, "Observation Provider Failure")
    try:
        runtime = ResearchHarnessRuntime(
            observation_provider=SourceObservationProvider("phase_g_source")
        )
        try:
            await runtime.run(
                ResearchHarnessInput(
                    user_id=user_id,
                    thread_id=thread_id,
                    objective="Record provider timeout without writing evidence.",
                    subquestions=["Can provider timeout be recorded structurally?"],
                    next_actions=["Ask provider and expect timeout."],
                    metadata={
                        "trace_id": "phase_g_harness_failure",
                        "provider": {
                            "force_status": "timeout",
                            "error": "simulated provider timeout",
                        },
                    },
                )
            )
        except HarnessFieldError as exc:
            _assert(
                "observation_batch.observations" in str(exc),
                "provider failure should block aggregation on missing observations",
            )
        else:
            raise AssertionError("provider failure should not proceed to aggregation")

        runs = await get_research_orchestrator().list_research_runs(
            user_id=user_id,
            status="active",
            limit=10,
        )
        _assert(len(runs.runs) == 1, "failed harness should leave one active run")
        run_id = runs.runs[0].id
        _assert(run_id is not None, "active failed run should have id")
        inspected = await get_research_orchestrator().inspect_research_state(
            user_id=user_id,
            run_id=run_id,
            limit_steps=20,
            limit_evidence=20,
        )
        search_steps = [step for step in inspected.steps if step.step_type == "search"]
        _assert(search_steps, "provider failure should still record search step")
        _assert(
            search_steps[-1].status == "timeout",
            "provider timeout should map to search step timeout",
        )
        _assert(
            search_steps[-1].error == "simulated provider timeout",
            "provider error should be recorded on search step",
        )
        _assert(inspected.evidence == [], "provider failure should not create evidence")
        _assert(
            await _memory_event_count(user_id) == 0,
            "provider failure must not write memory",
        )
    finally:
        await _delete_temp_user(user_id)


async def _run_observation_provider_flow() -> None:
    await _run_direct_provider_checks()
    await _run_harness_provider_success()
    await _run_harness_provider_failure()
    print("research observation provider verification passed")


async def _main(skip_migration: bool) -> None:
    load_dotenv()
    if not skip_migration:
        _init_postgres()
    init_embedding_model()
    await init_database()
    try:
        await _run_observation_provider_flow()
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
