from __future__ import annotations

import unittest

from app.services.agent_core.publication.deterministic import (
    DeterministicReceiptRenderer,
)
from app.services.agent_core.publication.memory_renderer import (
    render_memory_mutation,
    render_memory_search,
)
from app.services.agent_runtime.contracts import (
    ActionPlan,
    ActionReceipt,
    PlanReceipt,
    PlannedAction,
)
from app.services.agent_runtime.trace_redaction import redact_tool_args


class MemoryHistoryRenderTests(unittest.TestCase):
    def test_previous_name_renders_nearest_version(self) -> None:
        rendered = render_memory_search(
            {
                "status": "completed",
                "scope": "previous",
                "memories": [_name_mem("小白", version_no=2)],
            }
        )
        self.assertEqual(rendered, "你之前叫小白。")

    def test_previous_with_depth_renders_nearest_first(self) -> None:
        rendered = render_memory_search(
            {
                "status": "completed",
                "scope": "previous",
                "memories": [
                    _name_mem("小白", version_no=2),
                    _name_mem("小红", version_no=1),
                ],
            }
        )
        self.assertEqual(rendered, "你之前叫小白；更早叫小红。")

    def test_earliest_name_renders_chain_root(self) -> None:
        rendered = render_memory_search(
            {
                "status": "completed",
                "scope": "earliest",
                "memories": [_name_mem("小红", version_no=1)],
            }
        )
        self.assertEqual(rendered, "你最早叫小红。")

    def test_timeline_renders_full_chain(self) -> None:
        v1 = _name_mem(
            "小红",
            version_no=1,
            valid_from="2026-01-01T00:00:00+00:00",
            superseded_by="v2",
        )
        v2 = _name_mem(
            "小白",
            version_no=2,
            valid_from="2026-02-01T00:00:00+00:00",
            superseded_by="v3",
        )
        v3 = _name_mem(
            "小红",
            version_no=3,
            valid_from="2026-03-01T00:00:00+00:00",
        )
        rendered = render_memory_search(
            {
                "status": "completed",
                "scope": "timeline",
                "memories": [v1, v2, v3],
            }
        )
        self.assertEqual(
            rendered,
            "你的名字变更：小红 → 小白 → 小红（当前）。",
        )

    def test_current_possession_renders_entity(self) -> None:
        rendered = render_memory_search(
            {
                "status": "completed",
                "scope": "current",
                "memories": [
                    {
                        "schema_key": "possession.entity",
                        "memory_key": "possession.entity:x",
                        "value": {"entity": "猫"},
                        "qualifiers": {"entity_type": "pet"},
                    }
                ],
            }
        )
        self.assertIn("你有猫。", rendered)

    def test_revised_mutation_discloses_old_value(self) -> None:
        rendered = render_memory_mutation(
            {
                "status": "committed",
                "mutations": [
                    {
                        "memory_key": "identity.self_reported_name:self",
                        "status": "revised",
                        "version": _name_mem("小红", version_no=3),
                        "previous": _name_mem("小白", version_no=2),
                    }
                ],
            }
        )
        self.assertEqual(rendered, "已把你的名字从小白更新为小红。")


class DeterministicReadPriorityTests(unittest.TestCase):
    def _plan_and_receipt(
        self,
        *,
        search_output: dict,
        conversation_answer: str,
    ) -> tuple[ActionPlan, PlanReceipt]:
        plan = ActionPlan(
            source="controller_proposal",
            route_type="fast_path",
            intent="controller_capability_batch",
            response_mode="receipt",
            goal="我之前叫什么",
            actions=[
                PlannedAction(
                    action_id="conv",
                    capability="conversation",
                    operation="conversation_read",
                    arguments={
                        "target": "exchange",
                        "selection": "latest",
                        "count": 1,
                    },
                ),
                PlannedAction(
                    action_id="mem",
                    capability="memory",
                    operation="search_memory_v2",
                    arguments={"query": "之前叫什么", "scope": "previous"},
                ),
            ],
        )
        receipt = PlanReceipt(
            plan_id=plan.plan_id,
            request_id="request-history",
            route_type="fast_path",
            intent="controller_capability_batch",
            status="completed",
            actions=[
                ActionReceipt(
                    action_id="conv",
                    capability="conversation",
                    operation="conversation_read",
                    status="completed",
                    output={"answer": conversation_answer},
                ),
                ActionReceipt(
                    action_id="mem",
                    capability="memory",
                    operation="search_memory_v2",
                    status="completed",
                    output=search_output,
                ),
            ],
        )
        return plan, receipt

    def test_memory_answer_wins_over_conversation_transcript(self) -> None:
        plan, receipt = self._plan_and_receipt(
            search_output={
                "status": "completed",
                "scope": "previous",
                "memories": [_name_mem("小白", version_no=2)],
            },
            conversation_answer='你刚才说："我是谁？"',
        )
        answer = DeterministicReceiptRenderer().render(plan, receipt)
        self.assertIn("你之前叫小白", answer.content)
        self.assertNotIn("你刚才说", answer.content)

    def test_empty_memory_search_falls_back_to_conversation(self) -> None:
        plan, receipt = self._plan_and_receipt(
            search_output={
                "status": "empty",
                "scope": "previous",
                "memories": [],
            },
            conversation_answer='你刚才说："我是谁？"',
        )
        answer = DeterministicReceiptRenderer().render(plan, receipt)
        self.assertIn("你刚才说", answer.content)


class TraceRedactionTests(unittest.TestCase):
    def test_redaction_drops_system_fields_and_credentials(self) -> None:
        redacted = redact_tool_args(
            {
                "query": "你好",
                "user_id": "should-drop",
                "thread_id": "should-drop",
                "api_key": "sk-123456789012345",
                "nested": {"password": "secret", "ok": 1},
            }
        )
        self.assertNotIn("user_id", redacted)
        self.assertNotIn("thread_id", redacted)
        self.assertNotIn("api_key", redacted)
        self.assertEqual(redacted["nested"], {"ok": 1})


def _name_mem(
    name: str,
    *,
    version_no: int,
    valid_from: str = "2026-01-01T00:00:00+00:00",
    superseded_by=None,
) -> dict:
    return {
        "schema_key": "identity.self_reported_name",
        "memory_key": "identity.self_reported_name:self",
        "version_no": version_no,
        "subject": "self",
        "predicate": "name",
        "value": {"name": name},
        "qualifiers": {},
        "evidence_quote": f"I am {name}",
        "valid_from": valid_from,
        "valid_to": None,
        "superseded_by": superseded_by,
        "is_tombstone": False,
    }


if __name__ == "__main__":
    unittest.main()
