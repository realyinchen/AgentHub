"""Verify fixed Shadow gate thresholds without claiming a live canary."""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.services.agent_core.shadow_gate_contracts import (
    ShadowDecisionReview,
    ShadowCoverageSnapshot,
    ShadowGateDataset,
    ShadowGateObservation,
)
from app.services.agent_core.shadow_gate_evaluator import (
    ShadowGateEvaluator,
)


CONTROLLER_FINGERPRINT = "b" * 64
CONFIGURATION_FINGERPRINT = "a" * 64
START = datetime(2026, 7, 27, 2, tzinfo=timezone.utc)
WINDOW_END = START + timedelta(days=3)
DIFFERENCE_FINGERPRINT = "d" * 64


def _observation(index: int) -> ShadowGateObservation:
    has_difference = index == 13
    return ShadowGateObservation(
        observation_key=f"{index:064x}",
        created_at=START + timedelta(days=index % 3),
        source_commit_sha="c" * 40,
        controller_fingerprint=CONTROLLER_FINGERPRINT,
        configuration_fingerprint=CONFIGURATION_FINGERPRINT,
        controller_status="shadow_valid",
        journal_terminal_count=1,
        audit_receipt_count=0,
        difference_kind=(
            "decision_mode_changed"
            if has_difference
            else None
        ),
        difference_fingerprint=(
            DIFFERENCE_FINGERPRINT if has_difference else None
        ),
        review=(
            ShadowDecisionReview(
                classification="expected_improvement",
                severity="P2",
                explained=True,
                difference_fingerprint=DIFFERENCE_FINGERPRINT,
                reviewer_id="fixture-reviewer",
                reviewed_at=WINDOW_END,
                reason_codes=["fixture.expected_improvement"],
            )
            if has_difference
            else None
        ),
    )


def _dataset(
    observations: list[ShadowGateObservation],
) -> ShadowGateDataset:
    return ShadowGateDataset(
        commit_sha="c" * 40,
        controller_fingerprint=CONTROLLER_FINGERPRINT,
        configuration_fingerprint=CONFIGURATION_FINGERPRINT,
        prompt_version="controller-prompt-v1",
        window_started_at=START,
        window_ended_at=WINDOW_END,
        collected_at=WINDOW_END + timedelta(minutes=5),
        coverage=ShadowCoverageSnapshot(
            eligible=len(observations),
            observed=len(observations),
            pending_within_grace=0,
            missing_after_grace=0,
        ),
        observations=observations,
    )


def _run() -> None:
    evaluator = ShadowGateEvaluator()
    clean_observations = [
        _observation(index) for index in range(500)
    ]
    passed = evaluator.evaluate(_dataset(clean_observations))
    if passed.status != "passed":
        raise AssertionError(
            f"clean 500 Turn/3 day window did not pass: {passed}"
        )

    undersized = evaluator.evaluate(
        _dataset(clean_observations[:499])
    )
    if (
        undersized.status != "blocked"
        or "sample_count_below_500" not in undersized.reasons
    ):
        raise AssertionError("undersized window did not block")

    missing_dataset = _dataset(clean_observations)
    missing_dataset = missing_dataset.model_copy(
        update={
            "coverage": ShadowCoverageSnapshot(
                eligible=501,
                observed=500,
                pending_within_grace=0,
                missing_after_grace=1,
            )
        }
    )
    dropped = evaluator.evaluate(missing_dataset)
    if (
        dropped.status != "failed"
        or "enrollment_delivery_missing" not in dropped.reasons
    ):
        raise AssertionError("dropped Shadow command did not fail Gate")

    receipt_observations = list(clean_observations)
    receipt_observations[7] = receipt_observations[7].model_copy(
        update={"audit_receipt_count": 1}
    )
    receipt = evaluator.evaluate(_dataset(receipt_observations))
    if (
        receipt.status != "failed"
        or "shadow_audit_receipts_nonzero" not in receipt.reasons
    ):
        raise AssertionError("Shadow execution Receipt did not fail Gate")

    unreviewed_observations = list(clean_observations)
    unreviewed_observations[13] = (
        unreviewed_observations[13].model_copy(
            update={"review": None}
        )
    )
    unreviewed = evaluator.evaluate(
        _dataset(unreviewed_observations)
    )
    if (
        unreviewed.status != "blocked"
        or "unreviewed_differences_nonzero"
        not in unreviewed.reasons
    ):
        raise AssertionError(
            "unreviewed decision difference did not block"
        )

    print("controller shadow gate fixture verification passed")
    print("clean_window=passed")
    print("sample_count=500")
    print("consecutive_natural_days=3")
    print("undersized_window=blocked")
    print("durable_delivery_gap=failed")
    print("shadow_audit_receipt=failed")
    print("unreviewed_difference=blocked")
    print("live_shadow_evidence=false")


if __name__ == "__main__":
    _run()
