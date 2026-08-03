from __future__ import annotations

import unittest

from scripts.verify_agent_core_systems_matrix import (
    SYSTEM_SPECS,
    build_report,
    validate_verifier_output,
)


class AgentCoreSystemsMatrixTests(unittest.TestCase):
    def test_matrix_has_eight_unique_single_verifier_domains(self) -> None:
        self.assertEqual(
            [spec.domain_id for spec in SYSTEM_SPECS],
            [
                "planning",
                "execution",
                "tool_invocation",
                "state_management",
                "long_term_memory",
                "short_term_memory",
                "context_compression",
                "failure_recovery",
            ],
        )
        self.assertEqual(
            len({spec.verifier for spec in SYSTEM_SPECS}),
            len(SYSTEM_SPECS),
        )

    def test_report_never_grants_release_credit(self) -> None:
        results = [
            {"domain_id": spec.domain_id, "status": "passed"}
            for spec in SYSTEM_SPECS
        ]
        report = build_report(
            results,
            production_flags={"AGENT_CAPABILITY_TASK_V1": False},
        )
        self.assertEqual(report["status"], "passed")
        self.assertTrue(report["fixture_or_local_core_loop_passed"])
        self.assertFalse(report["release_gate_credit"])
        self.assertEqual(report["online_model_calls"], 0)

    def test_missing_marker_fails_closed(self) -> None:
        with self.assertRaisesRegex(AssertionError, "markers missing"):
            validate_verifier_output(SYSTEM_SPECS[0], "unrelated output")

    def test_enabled_production_flag_fails_report(self) -> None:
        results = [
            {"domain_id": spec.domain_id, "status": "passed"}
            for spec in SYSTEM_SPECS
        ]
        report = build_report(
            results,
            production_flags={"AGENT_CAPABILITY_TASK_V1": True},
        )
        self.assertEqual(report["status"], "failed")
        self.assertFalse(report["fixture_or_local_core_loop_passed"])


if __name__ == "__main__":
    unittest.main()
