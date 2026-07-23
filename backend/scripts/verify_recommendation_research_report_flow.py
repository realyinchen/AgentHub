"""Verify read-only recommendation + research report fusion.

This check avoids live web/LLM calls. It verifies:
- build_recommendation_research_report is gated by Deep Search / Deep Research intent
- only research-report-v1 verified_claims support recommendation candidates
- uncertain/rejected claims remain limitations and do not support candidates
- the fusion projector writes no memory, recommendation events, research steps,
  or evidence
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
from app.services.research import ResearchEvidence, get_research_orchestrator
from app.services.tool_admission import reset_tool_admission_gate
from app.utils.logging import request_id_scope
from app.utils.turn_context import user_message_scope
from scripts.init_database import _init_postgres


VERIFIED_CLAIM = "Fresh Warm Novel is warm and character-driven."
UNCERTAIN_CLAIM = "Fresh Warm Novel may have no bleak content."


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
            {"user_id": user_id, "display_name": "Recommendation Research Verify"},
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
                "title": "Recommendation Research Verify",
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


async def _recommendation_event_count(user_id: uuid.UUID) -> int:
    db = get_database()
    async with db.session() as session:
        count = await session.scalar(
            text(
                "SELECT COUNT(*) FROM public.recommendation_events "
                "WHERE user_id = :user_id"
            ),
            {"user_id": user_id},
        )
        return int(count or 0)


async def _research_step_count(run_id: str) -> int:
    db = get_database()
    async with db.session() as session:
        count = await session.scalar(
            text("SELECT COUNT(*) FROM public.research_steps WHERE run_id = :run_id"),
            {"run_id": run_id},
        )
        return int(count or 0)


async def _evidence_count(run_id: str) -> int:
    db = get_database()
    async with db.session() as session:
        count = await session.scalar(
            text("SELECT COUNT(*) FROM public.research_evidence WHERE run_id = :run_id"),
            {"run_id": run_id},
        )
        return int(count or 0)


async def _build_research_report(**payload: Any) -> dict[str, Any]:
    return json.loads(await research_tools.build_research_report.ainvoke(payload))


async def _build_recommendation_research_report(**payload: Any) -> dict[str, Any]:
    return json.loads(
        await research_tools.build_recommendation_research_report.ainvoke(payload)
    )


async def _run_recommendation_research_report_flow() -> None:
    user_id = uuid.uuid4()
    thread_id = uuid.uuid4()
    research = get_research_orchestrator()

    await _insert_temp_user_and_thread(user_id, thread_id)
    try:
        reset_tool_admission_gate()
        with request_id_scope("verify-recommendation-research-blocked"):
            with user_message_scope("Please recommend warm books."):
                blocked = await _build_recommendation_research_report(
                    query="warm books",
                    candidates=[{"title": "Fresh Warm Novel"}],
                    research_report={"contract_version": "research-report-v1"},
                )
        _assert(blocked["status"] == "tool_blocked", str(blocked))
        _assert(blocked["result_mode"] == "recommendation_research_report", str(blocked))

        started = await research.start_research(
            user_id=user_id,
            thread_id=thread_id,
            objective="Research warm recommendation candidates.",
            mode="deep_research",
            subquestions=["Is Fresh Warm Novel a warm candidate?"],
            gaps=[],
            next_actions=["Collect source-backed evidence."],
            budget={"required_evidence_quality": "medium"},
            stop_criteria=["One medium-quality claim is admitted."],
        )
        run_id = started.run.id
        _assert(run_id is not None, "run id should exist")
        assert run_id is not None

        await research.add_evidence(
            user_id=user_id,
            run_id=run_id,
            evidence=ResearchEvidence(
                run_id=run_id,
                source_type="web",
                source_title="Reliable Review",
                source_url="https://example.test/fresh-warm-review",
                claim=VERIFIED_CLAIM,
                excerpt="The review describes a gentle character-focused story.",
                quality="medium",
                relevance=5,
            ),
            known_facts=[VERIFIED_CLAIM],
        )
        await research.add_evidence(
            user_id=user_id,
            run_id=run_id,
            evidence=ResearchEvidence(
                run_id=run_id,
                source_type="web",
                source_title="Weak Forum Note",
                source_url="https://example.test/fresh-warm-forum",
                claim=UNCERTAIN_CLAIM,
                excerpt="A weak note says it is not bleak.",
                quality="low",
                relevance=3,
            ),
            known_facts=[UNCERTAIN_CLAIM],
        )

        reset_tool_admission_gate()
        with request_id_scope("verify-recommendation-research-fusion"):
            with user_message_scope(
                "Please deep research and recommend warm character-driven books."
            ):
                report = await _build_research_report(
                    user_id=str(user_id),
                    run_id=str(run_id),
                    limit_steps=100,
                    limit_evidence=100,
                )
                memory_count_before = await _memory_event_count(user_id)
                recommendation_count_before = await _recommendation_event_count(user_id)
                step_count_before = await _research_step_count(str(run_id))
                evidence_count_before = await _evidence_count(str(run_id))

                fused = await _build_recommendation_research_report(
                    query="warm character-driven books",
                    candidates=[
                        {
                            "id": str(uuid.uuid4()),
                            "title": "Fresh Warm Novel",
                            "authors": ["Example Author"],
                            "summary": "A gentle, warm, character-driven novel.",
                            "source_name": "book_cache",
                            "source_url": "https://example.test/fresh-warm",
                            "candidate_source": {
                                "candidate_source": "book_cache",
                                "reason": "matched local Book Cache",
                            },
                            "recommendation": {
                                "score": 1.42,
                                "suppressed": False,
                                "positive_reasons": [
                                    "matches memory preferred_tag: warm"
                                ],
                                "suppression_reasons": [],
                                "metadata": {
                                    "contract_version": (
                                        "recommendation-projection-v1"
                                    )
                                },
                            },
                            "recommendation_explanation": {
                                "contract_version": "recommendation-explanation-v1",
                                "positive_reasons": [
                                    "matches memory preferred_tag: warm"
                                ],
                                "suppression_reasons": [],
                            },
                        },
                        {
                            "id": str(uuid.uuid4()),
                            "title": "Unsupported Novel",
                            "authors": ["Other Author"],
                            "summary": "A candidate without research support.",
                            "recommendation": {
                                "score": 1.1,
                                "suppressed": False,
                                "positive_reasons": ["matches query terms"],
                            },
                        },
                    ],
                    research_report=report,
                )

        _assert(fused["result_mode"] == "recommendation_research_report", str(fused))
        _assert(
            fused["contract_version"] == "recommendation-research-report-v1",
            str(fused),
        )
        _assert(fused["status"] == "ok", str(fused))
        _assert(fused["candidate_count"] == 2, str(fused))
        _assert(fused["supported_count"] == 1, str(fused))
        _assert(fused["verified_claim_count"] == 1, str(fused))
        supported = fused["recommended_candidates"][0]
        _assert(supported["title"] == "Fresh Warm Novel", str(supported))
        _assert(
            supported["research_support"][0]["claim"] == VERIFIED_CLAIM,
            str(supported),
        )
        _assert(
            UNCERTAIN_CLAIM
            not in " ".join(
                support["claim"] for support in supported["research_support"]
            ),
            str(supported["research_support"]),
        )
        _assert(
            "some_candidates_lack_verified_research_support" in fused["limitations"],
            str(fused["limitations"]),
        )
        _assert(
            "uncertain_research_claims_omitted_from_support" in fused["limitations"],
            str(fused["limitations"]),
        )
        _assert(
            fused["metadata"]["uses_verified_claims_only"] is True,
            str(fused["metadata"]),
        )
        _assert(fused["metadata"]["external_call"] is False, str(fused["metadata"]))
        _assert(
            await _memory_event_count(user_id) == memory_count_before,
            "fusion should not write memory",
        )
        _assert(
            await _recommendation_event_count(user_id) == recommendation_count_before,
            "fusion should not write recommendation events",
        )
        _assert(
            await _research_step_count(str(run_id)) == step_count_before,
            "fusion should not write research steps",
        )
        _assert(
            await _evidence_count(str(run_id)) == evidence_count_before,
            "fusion should not write evidence",
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
        await _run_recommendation_research_report_flow()
    finally:
        await dispose_database()
    print("recommendation research report verification passed")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-migration", action="store_true")
    args = parser.parse_args()

    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(_main(skip_migration=args.skip_migration))


if __name__ == "__main__":
    main()
