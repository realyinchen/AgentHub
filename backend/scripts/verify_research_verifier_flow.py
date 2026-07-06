"""
Verify the Phase F verifier admission layer.

The direct checks cover admitted, rejected, uncertain, and conflict-blocked
claim sets. The harness check verifies explicit uncertainty finalization.

Usage:
    cd backend
    .\\.venv\\Scripts\\python.exe scripts\\verify_research_verifier_flow.py
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
from app.services.research import ResearchEvidence
from app.services.research.harness import (
    ResearchHarnessInput,
    ResearchHarnessRuntime,
    ResearchObservation,
)
from app.services.research.harness.contracts import HarnessFieldError
from app.services.research.verifier import (
    ClaimForVerification,
    ResearchVerifier,
    VerifierAdmissionInput,
)
from scripts.init_database import _init_postgres


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def _evidence(
    *,
    run_id: uuid.UUID,
    evidence_id: uuid.UUID,
    claim: str = "Example claim is supported.",
    quality: str = "medium",
    source_title: str = "Example Source",
    source_url: str = "https://example.test/source",
) -> ResearchEvidence:
    return ResearchEvidence(
        id=evidence_id,
        run_id=run_id,
        source_type="web",
        source_title=source_title,
        source_url=source_url,
        claim=claim,
        excerpt="A source-backed excerpt.",
        quality=quality,
        relevance=5,
    )


def _run_direct_verifier_checks() -> None:
    verifier = ResearchVerifier()
    run_id = uuid.uuid4()
    medium_id = uuid.uuid4()
    low_id = uuid.uuid4()
    unknown_id = uuid.uuid4()
    evidence = [
        _evidence(run_id=run_id, evidence_id=medium_id, quality="medium"),
        _evidence(
            run_id=run_id,
            evidence_id=low_id,
            claim="Low quality claim is weakly supported.",
            quality="low",
        ),
        _evidence(
            run_id=run_id,
            evidence_id=unknown_id,
            claim="Unknown quality claim is weakly supported.",
            quality="unknown",
        ),
    ]

    admitted = verifier.verify(
        VerifierAdmissionInput(
            run_id=run_id,
            candidate_claims=[
                ClaimForVerification(
                    claim="Example claim is supported.",
                    evidence_ids=[medium_id],
                    quality="medium",
                )
            ],
            evidence=evidence,
            exhausted_queries=["example query"],
            stop_criteria=["At least one claim has evidence."],
        )
    )
    _assert(admitted.ready_for_final_answer, "medium evidence should be ready")
    _assert(len(admitted.admitted_claims) == 1, "medium evidence should admit claim")
    _assert(
        admitted.admitted_claims[0].reason_codes == ["supported_by_evidence"],
        "admitted claim should record support reason",
    )

    rejected = verifier.verify(
        VerifierAdmissionInput(
            run_id=run_id,
            candidate_claims=[
                ClaimForVerification(
                    claim="Unsupported claim should be rejected.",
                    evidence_ids=[],
                    quality="medium",
                )
            ],
            evidence=evidence,
            stop_criteria=["At least one claim has evidence."],
        )
    )
    _assert(not rejected.ready_for_final_answer, "missing evidence should block final")
    _assert(len(rejected.rejected_claims) == 1, "missing evidence should reject claim")
    _assert(
        "missing_evidence" in rejected.rejected_claims[0].reason_codes,
        "rejected claim should record missing evidence",
    )

    uncertain = verifier.verify(
        VerifierAdmissionInput(
            run_id=run_id,
            candidate_claims=[
                ClaimForVerification(
                    claim="Low quality claim is weakly supported.",
                    evidence_ids=[low_id],
                    quality="low",
                ),
                ClaimForVerification(
                    claim="Unknown quality claim is weakly supported.",
                    evidence_ids=[unknown_id],
                    quality="unknown",
                ),
            ],
            evidence=evidence,
            stop_criteria=["At least one claim has evidence."],
        )
    )
    _assert(not uncertain.ready_for_final_answer, "weak evidence should not be final by default")
    _assert(len(uncertain.uncertain_claims) == 2, "weak evidence should be uncertain")
    reason_codes = {
        reason
        for claim in uncertain.uncertain_claims
        for reason in claim.reason_codes
    }
    _assert(
        {"low_quality_evidence", "unknown_quality_evidence"} <= reason_codes,
        "uncertain claims should record quality reasons",
    )

    explicit_uncertainty = verifier.verify(
        VerifierAdmissionInput(
            run_id=run_id,
            candidate_claims=[
                ClaimForVerification(
                    claim="Low quality claim is weakly supported.",
                    evidence_ids=[low_id],
                    quality="low",
                )
            ],
            evidence=evidence,
            budget={"allow_uncertain_final_answer": True},
            stop_criteria=["At least one claim has evidence."],
        )
    )
    _assert(
        explicit_uncertainty.ready_for_final_answer,
        "explicit uncertainty should allow final uncertainty answer",
    )
    _assert(
        explicit_uncertainty.can_finalize_with_uncertainty,
        "uncertainty finalization should be explicit in the result",
    )

    conflicted = verifier.verify(
        VerifierAdmissionInput(
            run_id=run_id,
            candidate_claims=[
                ClaimForVerification(
                    claim="Example claim is supported.",
                    evidence_ids=[medium_id],
                    quality="medium",
                )
            ],
            evidence=evidence,
            conflicts=["Another source contradicts the tone claim."],
            stop_criteria=["At least one claim has evidence."],
        )
    )
    _assert(not conflicted.ready_for_final_answer, "unresolved conflict should block final")
    _assert(
        "unresolved_conflict" in conflicted.metadata["reason_codes"],
        "conflict should be recorded as a global admission reason",
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
            {"user_id": user_id, "display_name": "Research Verifier Verify"},
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
                "title": "Research Verifier Verify",
            },
        )


async def _delete_temp_user(user_id: uuid.UUID) -> None:
    db = get_database()
    async with db.session() as session:
        await session.execute(
            text("DELETE FROM public.users WHERE id = :user_id"),
            {"user_id": user_id},
        )


async def _run_uncertainty_harness_check() -> None:
    user_id = uuid.uuid4()
    thread_id = uuid.uuid4()
    await _insert_temp_user_and_thread(user_id, thread_id)
    try:
        runtime = ResearchHarnessRuntime()
        result = await runtime.run(
            ResearchHarnessInput(
                user_id=user_id,
                thread_id=thread_id,
                objective="Return an explicit uncertainty answer for weak evidence.",
                subquestions=["Can weak evidence support this candidate?"],
                next_actions=["Collect a weak source and verify with uncertainty."],
                budget={"allow_uncertain_final_answer": True},
                stop_criteria=["At least one claim has evidence."],
                observations=[
                    ResearchObservation(
                        source_type="web",
                        source_title="Weak Source",
                        source_url="https://example.test/weak-source",
                        claim="Weak Candidate may fit the recommendation.",
                        excerpt="The source is too weak for a verified finding.",
                        quality="low",
                        relevance=3,
                    )
                ],
                metadata={"trace_id": "phase_f_uncertainty_harness"},
            )
        )
        _assert(result.status == "completed", "uncertainty harness run should complete")
        _assert(
            result.finalization.verified_claims == [],
            "uncertain final answer should not create verified claims",
        )
        _assert(
            "Remaining uncertainty" in result.finalization.final_answer,
            "uncertain final answer should label uncertainty explicitly",
        )
        _assert(
            result.finalization.remaining_uncertainty,
            "uncertain final answer should expose uncertainty details",
        )
    finally:
        await _delete_temp_user(user_id)


async def _run_blocked_harness_check() -> None:
    user_id = uuid.uuid4()
    thread_id = uuid.uuid4()
    await _insert_temp_user_and_thread(user_id, thread_id)
    try:
        runtime = ResearchHarnessRuntime()
        try:
            await runtime.run(
                ResearchHarnessInput(
                    user_id=user_id,
                    thread_id=thread_id,
                    objective="Block finalization for weak evidence by default.",
                    subquestions=["Can weak evidence support a verified claim?"],
                    next_actions=["Collect a weak source and verify."],
                    stop_criteria=["At least one claim has evidence."],
                    observations=[
                        ResearchObservation(
                            source_type="web",
                            source_title="Weak Source",
                            source_url="https://example.test/weak-source-blocked",
                            claim="Weak Candidate should not become verified.",
                            excerpt="The source is too weak for a verified finding.",
                            quality="low",
                            relevance=3,
                        )
                    ],
                    metadata={"trace_id": "phase_f_blocked_harness"},
                )
            )
        except HarnessFieldError as exc:
            _assert(
                "verification.ready_for_final_answer" in str(exc),
                "blocked finalizer should cite missing ready field",
            )
            return
        raise AssertionError("weak evidence should block finalization by default")
    finally:
        await _delete_temp_user(user_id)


async def _main(skip_migration: bool) -> None:
    load_dotenv()
    if not skip_migration:
        _init_postgres()
    init_embedding_model()
    await init_database()
    try:
        _run_direct_verifier_checks()
        await _run_blocked_harness_check()
        await _run_uncertainty_harness_check()
        print("research verifier verification passed")
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
