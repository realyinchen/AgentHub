from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from app.services.agent_core.shadow_gate_contracts import (
    ShadowDecisionReview,
    ShadowCoverageSnapshot,
    ShadowGateDataset,
    ShadowGateObservation,
)
from app.services.agent_core.shadow_gate_evaluator import (
    ShadowGateEvaluator,
)


CONTROLLER_FP = "b" * 64
CONFIG_FP = "a" * 64
START = datetime(2026, 7, 27, 2, tzinfo=timezone.utc)
WINDOW_END = START + timedelta(days=3)
DIFFERENCE_FP = "d" * 64


def _observation(
    index: int,
    *,
    day: int | None = None,
    audit_receipt_count: int = 0,
    difference_kind: str | None = None,
    review: ShadowDecisionReview | None = None,
    source_commit_sha: str = "c" * 40,
) -> ShadowGateObservation:
    selected_day = day if day is not None else index % 3
    return ShadowGateObservation(
        observation_key=f"{index:064x}",
        created_at=START + timedelta(days=selected_day),
        source_commit_sha=source_commit_sha,
        controller_fingerprint=CONTROLLER_FP,
        configuration_fingerprint=CONFIG_FP,
        controller_status="shadow_valid",
        journal_terminal_count=1,
        audit_receipt_count=audit_receipt_count,
        difference_kind=difference_kind,
        difference_fingerprint=(
            DIFFERENCE_FP if difference_kind else None
        ),
        review=review,
    )


def _dataset(
    observations: list[ShadowGateObservation],
    *,
    missing_after_grace: int = 0,
    pending_within_grace: int = 0,
) -> ShadowGateDataset:
    observed = len(observations)
    return ShadowGateDataset(
        commit_sha="c" * 40,
        controller_fingerprint=CONTROLLER_FP,
        configuration_fingerprint=CONFIG_FP,
        prompt_version="controller-prompt-v1",
        window_started_at=START,
        window_ended_at=WINDOW_END,
        collected_at=WINDOW_END + timedelta(minutes=5),
        coverage=ShadowCoverageSnapshot(
            eligible=(
                observed
                + missing_after_grace
                + pending_within_grace
            ),
            observed=observed,
            pending_within_grace=pending_within_grace,
            missing_after_grace=missing_after_grace,
        ),
        observations=observations,
    )


class ShadowGateEvaluatorTests(unittest.TestCase):
    def test_less_than_500_turns_is_blocked(self) -> None:
        report = ShadowGateEvaluator().evaluate(
            _dataset(
                [_observation(index) for index in range(499)]
            )
        )

        self.assertEqual(report.status, "blocked")
        self.assertIn("sample_count_below_500", report.reasons)

    def test_three_consecutive_days_are_required(self) -> None:
        observations = [
            _observation(index, day=(0 if index < 250 else 2))
            for index in range(500)
        ]
        report = ShadowGateEvaluator().evaluate(
            _dataset(observations)
        )

        self.assertEqual(report.status, "blocked")
        self.assertIn(
            "consecutive_natural_days_below_3",
            report.reasons,
        )

    def test_drop_or_shadow_receipt_is_failed(self) -> None:
        observations = [
            _observation(
                index,
                audit_receipt_count=(1 if index == 7 else 0),
            )
            for index in range(500)
        ]
        report = ShadowGateEvaluator().evaluate(
            _dataset(observations, missing_after_grace=1)
        )

        self.assertEqual(report.status, "failed")
        self.assertIn("enrollment_delivery_missing", report.reasons)
        self.assertIn("shadow_audit_receipts_nonzero", report.reasons)
        self.assertEqual(report.error_observation_keys, [f"{7:064x}"])

    def test_unreviewed_difference_is_blocked(self) -> None:
        observations = [
            _observation(
                index,
                difference_kind=(
                    "capability_set_changed"
                    if index == 11
                    else None
                ),
            )
            for index in range(500)
        ]
        report = ShadowGateEvaluator().evaluate(
            _dataset(observations)
        )

        self.assertEqual(report.status, "blocked")
        self.assertIn(
            "unreviewed_differences_nonzero",
            report.reasons,
        )

    def test_complete_clean_window_passes(self) -> None:
        observations = [
            _observation(
                index,
                difference_kind=(
                    "decision_mode_changed"
                    if index == 13
                    else None
                ),
                review=(
                    ShadowDecisionReview(
                        classification="expected_improvement",
                        severity="P2",
                        explained=True,
                        difference_fingerprint=DIFFERENCE_FP,
                        reviewer_id="release-reviewer",
                        reviewed_at=WINDOW_END,
                        reason_codes=["expected.routing_improvement"],
                    )
                    if index == 13
                    else None
                ),
            )
            for index in range(500)
        ]
        report = ShadowGateEvaluator().evaluate(
            _dataset(observations)
        )

        self.assertEqual(report.status, "passed")
        self.assertEqual(report.sample_count, 500)
        self.assertEqual(report.max_consecutive_natural_days, 3)
        self.assertFalse(report.reasons)

    def test_mixed_source_commit_is_failed(self) -> None:
        observations = [
            _observation(
                index,
                source_commit_sha=(
                    "d" * 40 if index == 17 else "c" * 40
                ),
            )
            for index in range(500)
        ]
        report = ShadowGateEvaluator().evaluate(
            _dataset(observations)
        )

        self.assertEqual(report.status, "failed")
        self.assertIn("source_commit_mixed", report.reasons)
        self.assertIn(f"{17:064x}", report.error_observation_keys)


if __name__ == "__main__":
    unittest.main()
