from __future__ import annotations

import unittest

from scripts.verify_agent_core_acceptance_matrix import (
    CASE_SPECS,
    CONVERSATION_SPEC,
    build_report,
)


class AgentCoreAcceptanceMatrixTests(unittest.TestCase):
    def test_six_case_contract_is_exact(self) -> None:
        self.assertEqual(
            [
                (
                    item.case_id,
                    item.user_input,
                    item.expected_capability,
                )
                for item in CASE_SPECS
            ],
            [
                ("identity_read", "我是谁？", "search_memory"),
                (
                    "identity_update",
                    "我现在不叫冰露，我现在叫鲁班",
                    "remember_memory",
                ),
                ("weather_current", "今天北京天气怎么样？", "weather_get"),
                ("simple_direct", "什么是递归？", "direct_answer"),
                (
                    "external_current_fact",
                    "法国总统是谁？",
                    "web_search",
                ),
                (
                    "deep_book_research",
                    "深度搜索下最新的好评图书",
                    "research_start",
                ),
            ],
        )

    def test_matrix_uses_only_modern_domain_verifiers(self) -> None:
        verifiers = {item.verifier for item in (*CASE_SPECS, CONVERSATION_SPEC)}
        self.assertNotIn("verify_routing_decision_flow.py", verifiers)
        self.assertEqual(CONVERSATION_SPEC.expected_capability, "conversation_read")

    def test_fixture_report_never_grants_release_credit(self) -> None:
        results = [
            {"case_id": item.case_id, "status": "passed"}
            for item in (*CASE_SPECS, CONVERSATION_SPEC)
        ]
        report = build_report(results)
        self.assertEqual(report["status"], "passed")
        self.assertTrue(report["local_core_loop_passed"])
        self.assertFalse(report["release_gate_credit"])
        self.assertEqual(report["online_model_calls"], 0)
        self.assertEqual(report["legacy_router_cases"], 0)


if __name__ == "__main__":
    unittest.main()
