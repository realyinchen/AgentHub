"""
Verify Phase I mem0/gbrain provider routing and configuration.

This check verifies:
- provider configuration uses app-owned fields/capabilities
- mem0 recall cannot resurrect forgotten or superseded memories
- gbrain observations become research evidence only through the harness
- gbrain output cannot bypass verifier admission

Usage:
    cd backend
    .\\.venv\\Scripts\\python.exe scripts\\verify_provider_routing_flow.py
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import uuid
from pathlib import Path

from dotenv import load_dotenv
from pydantic import ValidationError
from sqlalchemy import text

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.infra.database import dispose_database, get_database, init_database
from app.infra.llm.embedding import init_embedding_model
from app.services.memory import Mem0MemoryProvider, MemoryEvent, MemoryOrchestrator
from app.services.provider_config import AppProviderConfig, ProviderRegistry
from app.services.research import (
    GBrainObservationProvider,
    ResearchObservation,
    get_research_orchestrator,
)
from app.services.research.harness import ResearchHarnessInput, ResearchHarnessRuntime
from app.services.research.harness.contracts import HarnessFieldError
from app.services.research.observation_providers import ObservationProviderRequest
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


def _run_provider_config_checks() -> None:
    mem0 = AppProviderConfig(
        provider_key="mem0",
        provider_type="memory",
        enabled=True,
        display_name="mem0",
        capabilities=["memory_recall", "semantic_search"],
        settings={"seed_memories": []},
    )
    gbrain = AppProviderConfig(
        provider_key="gbrain",
        provider_type="research_observation",
        enabled=True,
        display_name="gbrain",
        capabilities=["research_observation", "source_visit"],
        settings={"seed_observations": []},
    )
    registry = ProviderRegistry([mem0, gbrain])
    _assert(
        registry.enabled_configs(
            provider_type="memory",
            capability="memory_recall",
        )
        == [mem0],
        "registry should expose enabled memory recall providers",
    )
    _assert(
        registry.enabled_configs(
            provider_type="research_observation",
            capability="research_observation",
        )
        == [gbrain],
        "registry should expose enabled research observation providers",
    )
    try:
        AppProviderConfig(
            provider_key="bad-provider",
            provider_type="memory",
            capabilities=["provider_native_capability"],
        )
    except ValidationError:
        pass
    else:
        raise AssertionError("provider-native capability should be rejected")


async def _run_mem0_current_memory_gate_check() -> None:
    user_id = uuid.uuid4()
    thread_id = uuid.uuid4()
    await _insert_temp_user_and_thread(user_id, thread_id, "Phase I mem0 Verify")
    postgres_orchestrator = MemoryOrchestrator(memory_recall_providers=[])
    try:
        active = await postgres_orchestrator.remember_memory(
            MemoryEvent(
                user_id=user_id,
                thread_id=thread_id,
                type="preference",
                subject="style",
                value="quiet family saga",
                polarity="like",
                confidence=0.95,
                source="chat_turn",
            )
        )
        old = await postgres_orchestrator.remember_memory(
            MemoryEvent(
                user_id=user_id,
                thread_id=thread_id,
                type="preference",
                subject="content",
                value="bloody suspense",
                polarity="avoid",
                confidence=0.9,
                source="chat_turn",
            )
        )
        revised = await postgres_orchestrator.revise_memory(
            user_id=user_id,
            old_value="bloody suspense",
            old_subject="content",
            old_type="preference",
            new_event=MemoryEvent(
                user_id=user_id,
                thread_id=thread_id,
                type="correction",
                subject="content",
                value="bloody or too dark suspense",
                polarity="avoid",
                confidence=0.98,
                source="chat_turn",
            ),
        )
        await postgres_orchestrator.forget_memory(
            user_id=user_id,
            memory_id=revised.id,
            thread_id=thread_id,
            reason="phase i mem0 verification",
        )

        mem0_seed = [
            {
                "type": active.type,
                "subject": active.subject,
                "value": active.value,
                "polarity": active.polarity,
                "confidence": active.confidence,
                "user_id": str(user_id),
                "source": "tool",
            },
            {
                "id": str(old.id),
                "type": old.type,
                "subject": old.subject,
                "value": old.value,
                "polarity": old.polarity,
                "confidence": old.confidence,
                "user_id": str(user_id),
                "source": "tool",
            },
            {
                "id": str(revised.id),
                "type": revised.type,
                "subject": revised.subject,
                "value": revised.value,
                "polarity": revised.polarity,
                "confidence": revised.confidence,
                "user_id": str(user_id),
                "source": "tool",
            },
        ]
        enhanced_orchestrator = MemoryOrchestrator(
            memory_recall_providers=[Mem0MemoryProvider(seed_memories=mem0_seed)]
        )
        result = await enhanced_orchestrator.search_memory(
            user_id=user_id,
            thread_id=thread_id,
            query="warm multigenerational relationships",
            memory_types=["preference", "correction"],
            limit=10,
        )
        values = {event.value for event in result.relevant_events}
        _assert(
            "quiet family saga" in values,
            "mem0 should be allowed to recall a matching current memory",
        )
        _assert(
            "bloody suspense" not in values,
            "mem0 must not resurrect superseded memory",
        )
        _assert(
            "bloody or too dark suspense" not in values,
            "mem0 must not resurrect forgotten memory",
        )
        _assert("mem0" in result.provider_sources, "mem0 provider source should be recorded")
        telemetry = [
            item for item in result.provider_telemetry if item["provider_name"] == "mem0"
        ]
        _assert(telemetry and telemetry[0]["status"] == "completed", "mem0 telemetry required")
    finally:
        await _delete_temp_user(user_id)


async def _run_gbrain_success_check() -> None:
    user_id = uuid.uuid4()
    thread_id = uuid.uuid4()
    await _insert_temp_user_and_thread(user_id, thread_id, "Phase I gbrain Success")
    try:
        before_memory_count = await _memory_event_count(user_id)
        runtime = ResearchHarnessRuntime(
            observation_provider=GBrainObservationProvider(
                seed_observations=[
                    ResearchObservation(
                        source_type="web",
                        source_title="gbrain Source",
                        source_url="https://example.test/gbrain-source",
                        claim="GBrain Candidate is source-backed and warm.",
                        excerpt="The source describes warmth and character focus.",
                        quality="medium",
                        relevance=5,
                    )
                ]
            )
        )
        result = await runtime.run(
            ResearchHarnessInput(
                user_id=user_id,
                thread_id=thread_id,
                objective="Verify gbrain observation routing.",
                subquestions=["Which gbrain observation has evidence?"],
                next_actions=["Ask gbrain through the observation provider."],
                stop_criteria=["One gbrain claim is admitted."],
                metadata={"trace_id": "phase_i_gbrain_success"},
            )
        )
        _assert(result.status == "completed", "gbrain-backed run should complete")
        _assert(result.finalization.verified_claims, "verified claims should exist")
        evidence = result.research_state.evidence[0]
        _assert(
            evidence.metadata["provider_source"] == "gbrain",
            "evidence should preserve gbrain provider source",
        )
        _assert(
            await _memory_event_count(user_id) == before_memory_count == 0,
            "gbrain must not write long-term memory",
        )
    finally:
        await _delete_temp_user(user_id)


async def _run_gbrain_verifier_gate_check() -> None:
    user_id = uuid.uuid4()
    thread_id = uuid.uuid4()
    await _insert_temp_user_and_thread(user_id, thread_id, "Phase I gbrain Gate")
    try:
        runtime = ResearchHarnessRuntime(
            observation_provider=GBrainObservationProvider(
                seed_observations=[
                    ResearchObservation(
                        source_type="web",
                        source_title="Weak gbrain Source",
                        source_url="https://example.test/gbrain-weak-source",
                        claim="Weak gbrain candidate should not become verified.",
                        excerpt="The source quality is too weak for a final claim.",
                        quality="low",
                        relevance=3,
                    )
                ]
            )
        )
        try:
            await runtime.run(
                ResearchHarnessInput(
                    user_id=user_id,
                    thread_id=thread_id,
                    objective="Block weak gbrain observations from final answers.",
                    subquestions=["Can weak gbrain evidence be finalized?"],
                    next_actions=["Verify low-quality gbrain evidence."],
                    stop_criteria=["Only verified claims may enter final answers."],
                    metadata={"trace_id": "phase_i_gbrain_verifier_gate"},
                )
            )
        except HarnessFieldError as exc:
            _assert(
                "verification.ready_for_final_answer" in str(exc),
                "weak gbrain evidence should be blocked by verifier readiness",
            )
        else:
            raise AssertionError("weak gbrain evidence should not finalize")

        runs = await get_research_orchestrator().list_research_runs(
            user_id=user_id,
            status="active",
            limit=10,
        )
        _assert(len(runs.runs) == 1, "blocked gbrain run should remain active")
        run_id = runs.runs[0].id
        _assert(run_id is not None, "blocked gbrain run should have an id")
        inspected = await get_research_orchestrator().inspect_research_state(
            user_id=user_id,
            run_id=run_id,
            limit_steps=50,
            limit_evidence=50,
        )
        _assert(inspected.evidence, "weak gbrain observation may become evidence")
        _assert(
            inspected.evidence[0].metadata["provider_source"] == "gbrain",
            "weak evidence should still preserve provider metadata",
        )
        _assert(
            all(step.step_type != "finish" for step in inspected.steps),
            "blocked gbrain run must not create a final answer step",
        )
        _assert(await _memory_event_count(user_id) == 0, "blocked gbrain run must not write memory")
    finally:
        await _delete_temp_user(user_id)


async def _run_gbrain_failure_mapping_check() -> None:
    result = await GBrainObservationProvider().observe(
        ObservationProviderRequest(
            run_id=uuid.uuid4(),
            query="forced gbrain timeout",
            metadata={
                "provider": {
                    "force_status": "timeout",
                    "error": "simulated gbrain timeout",
                }
            },
        )
    )
    _assert(result.status == "timeout", "gbrain timeout should map to timeout")
    _assert(result.error == "simulated gbrain timeout", "gbrain error should be recorded")
    _assert(result.observations == [], "failed gbrain result should not emit observations")


async def _run_provider_routing_flow() -> None:
    _run_provider_config_checks()
    await _run_mem0_current_memory_gate_check()
    await _run_gbrain_success_check()
    await _run_gbrain_verifier_gate_check()
    await _run_gbrain_failure_mapping_check()
    print("provider routing verification passed")


async def _main(skip_migration: bool) -> None:
    load_dotenv()
    if not skip_migration:
        _init_postgres()
    init_embedding_model()
    await init_database()
    try:
        await _run_provider_routing_flow()
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
