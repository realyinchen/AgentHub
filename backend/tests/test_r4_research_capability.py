from __future__ import annotations

import unittest
from uuid import uuid4

from app.services.agent_core.capabilities import CapabilityRegistry
from app.services.agent_core.compiler import WorkflowCompiler
from app.services.agent_core.contracts import (
    ControllerOutput,
    ControllerToolCall,
)
from app.services.agent_core.proposal_validator import ProposalValidator
from app.services.agent_core.plan_graph import PlanGraphNormalizer
from app.services.agent_runtime.contracts import ExecutionContext
from app.services.agent_runtime.runtime import SystemRuntime
from app.services.external_capabilities.availability import (
    ExternalCapabilityAvailability,
)
from app.services.external_capabilities.research import (
    ResearchEvidenceAdmissionAdapter,
    ResearchPrepareAdapter,
    ResearchReportAdapter,
    ResearchSearchAdapter,
)
from app.services.external_capabilities.runtime import (
    ExternalCapabilityRuntime,
)
from app.services.external_search.contracts import SearchHit, SearchResult
from app.services.tasks.contracts import TaskPlanDraft, TaskPlanStepDraft
from app.services.tasks.draft_validator import TaskPlanDraftValidator


RESEARCH_OPERATIONS = [
    "research_prepare_v1",
    "research_search_v1",
    "research_admit_evidence_v1",
    "research_report_v1",
]


def _availability(*, research: bool) -> ExternalCapabilityAvailability:
    return ExternalCapabilityAvailability(research_start=research)


def _research_output() -> ControllerOutput:
    return ControllerOutput(
        mode="capability_proposals",
        tool_calls=[
            ControllerToolCall(
                call_id="research",
                name="research_start",
                arguments={
                    "objective": "研究近三年中国科幻文学的发展趋势",
                    "mode": "deep_research",
                    "subquestions": [
                        "主要出版趋势是什么？",
                        "重要奖项和作者有哪些？",
                    ],
                    "constraints": ["只使用可引用公开来源"],
                    "max_sources": 6,
                    "max_rounds": 2,
                    "time_range": "year",
                    "language": "zh-CN",
                },
            )
        ],
    )


def _compile_research_plan():
    registry = CapabilityRegistry(
        availability=_availability(research=True)
    )
    batch = ProposalValidator(registry).validate(_research_output())
    return PlanGraphNormalizer().normalize(
        WorkflowCompiler().compile(
            batch,
            goal="深度研究近三年中国科幻文学的发展趋势。",
        )
    )


class _ResearchGatewayStub:
    async def search(self, request):
        return SearchResult(
            outcome="found",
            provider="private-research-provider",
            query=request.query,
            effective_query=request.query,
            hits=[
                SearchHit(
                    title="中国科幻出版观察",
                    url="https://research.example/scifi",
                    snippet="近三年科幻出版品种增加，青年作者受到关注。",
                    content="RAW_RESEARCH_DOCUMENT",
                    provider="private-research-provider",
                    metadata={"raw": "must-not-leak"},
                ),
                SearchHit(
                    title="无效来源",
                    url="javascript:alert(1)",
                    snippet="不得准入。",
                    provider="private-research-provider",
                ),
            ],
            metadata={"provider_dump": "must-not-leak"},
        )


class ResearchCapabilityContractTests(unittest.TestCase):
    def test_research_schema_exposes_goal_and_budget_not_runtime_identity(self):
        registry = CapabilityRegistry(
            availability=_availability(research=True)
        )
        spec = registry.get("research_start")
        self.assertIsNotNone(spec)
        self.assertFalse(spec.side_effect)
        properties = set(spec.input_model.model_json_schema()["properties"])
        self.assertEqual(
            properties,
            {
                "objective",
                "mode",
                "subquestions",
                "constraints",
                "max_sources",
                "max_rounds",
                "time_range",
                "language",
            },
        )
        self.assertTrue(
            {
                "user_id",
                "thread_id",
                "run_id",
                "provider",
                "action_id",
                "next_actions",
            }.isdisjoint(properties)
        )

    def test_research_compiler_owns_one_continuous_dependency_graph(self):
        plan = _compile_research_plan()

        self.assertEqual(plan.response_mode, "model")
        self.assertEqual(
            [item.operation for item in plan.actions],
            RESEARCH_OPERATIONS,
        )
        for index, action in enumerate(plan.actions):
            expected = [] if index == 0 else [plan.actions[index - 1].action_id]
            self.assertEqual(action.depends_on, expected)
        self.assertTrue(plan.metadata["graph_normalized"])

    def test_research_start_cannot_be_a_half_compiled_task_step(self):
        registry = CapabilityRegistry(
            availability=_availability(research=True)
        )
        draft = TaskPlanDraft(
            goal="研究科幻文学趋势",
            steps=[
                TaskPlanStepDraft(
                    step_key="research",
                    title="完成研究",
                    capability="research_start",
                    arguments={
                        "objective": "研究科幻文学趋势",
                    },
                )
            ],
        )

        with self.assertRaisesRegex(
            ValueError,
            "durable task step",
        ):
            TaskPlanDraftValidator(registry).validate(draft)


class ResearchCapabilityRuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def test_disabled_research_runtime_rejects_first_stage(self):
        plan = _compile_research_plan()
        runtime = ExternalCapabilityRuntime(
            availability=_availability(research=False),
            adapters=[
                ResearchPrepareAdapter(),
                ResearchSearchAdapter(
                    search_gateway=_ResearchGatewayStub()
                ),
                ResearchEvidenceAdmissionAdapter(),
                ResearchReportAdapter(),
            ],
        )

        receipt = await SystemRuntime(
            external_runtime=runtime
        ).execute(
            plan,
            context=ExecutionContext(
                user_id=uuid4(),
                thread_id=uuid4(),
                request_id="r4-research-disabled",
            ),
        )

        self.assertEqual(receipt.actions[0].status, "blocked")
        self.assertFalse(receipt.actions[0].admitted)
        self.assertTrue(
            all(
                item.status in {"blocked", "skipped"}
                for item in receipt.actions
            )
        )

    async def test_research_report_uses_only_admitted_sanitized_sources(self):
        plan = _compile_research_plan()
        enabled = _availability(research=True)
        runtime = ExternalCapabilityRuntime(
            availability=enabled,
            adapters=[
                ResearchPrepareAdapter(),
                ResearchSearchAdapter(
                    search_gateway=_ResearchGatewayStub()
                ),
                ResearchEvidenceAdmissionAdapter(),
                ResearchReportAdapter(),
            ],
        )

        receipt = await SystemRuntime(
            external_runtime=runtime
        ).execute(
            plan,
            context=ExecutionContext(
                user_id=uuid4(),
                thread_id=uuid4(),
                request_id="r4-research-success",
            ),
        )

        self.assertEqual(receipt.status, "completed")
        self.assertEqual(
            [item.status for item in receipt.actions],
            ["completed"] * 4,
        )
        output = receipt.actions[-1].output
        self.assertEqual(output["result_mode"], "research_report_evidence")
        self.assertEqual(output["status"], "ok")
        self.assertGreaterEqual(len(output["sources"]), 1)
        serialized = str(output)
        for forbidden in (
            "private-research-provider",
            "RAW_RESEARCH_DOCUMENT",
            "javascript:",
            "provider_dump",
            "must-not-leak",
        ):
            self.assertNotIn(forbidden, serialized)


if __name__ == "__main__":
    unittest.main()
