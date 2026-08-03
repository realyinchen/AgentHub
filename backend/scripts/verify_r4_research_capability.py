"""Verify the R4 ephemeral research workflow without database/provider I/O."""

# ruff: noqa: E402

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.services.agent_core.capabilities import CapabilityRegistry
from app.services.agent_core.compiler import WorkflowCompiler
from app.services.agent_core.contracts import (
    ControllerOutput,
    ControllerToolCall,
)
from app.services.agent_core.plan_graph import PlanGraphNormalizer
from app.services.agent_core.proposal_validator import ProposalValidator
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
from app.services.external_capabilities.research_compiler import (
    RESEARCH_STAGE_OPERATIONS,
)
from app.services.external_capabilities.runtime import (
    ExternalCapabilityRuntime,
)
from app.services.external_search.contracts import SearchHit, SearchResult


class _FixtureGateway:
    async def search(self, request):
        return SearchResult(
            outcome="found",
            provider="fixture-provider",
            query=request.query,
            hits=[
                SearchHit(
                    title="近期好评图书观察",
                    url="https://research.example/recent-books",
                    snippet="近期获得可靠书评来源好评的图书。",
                    content="RAW_FIXTURE_BODY",
                    provider="fixture-provider",
                    metadata={"raw": "must-not-leak"},
                ),
                SearchHit(
                    title="不安全来源",
                    url="javascript:alert(1)",
                    snippet="不得准入。",
                    provider="fixture-provider",
                ),
            ],
        )


async def _main() -> int:
    enabled = ExternalCapabilityAvailability(research_start=True)
    registry = CapabilityRegistry(availability=enabled)
    spec = registry.get("research_start")
    assert spec is not None
    assert spec.side_effect is False
    assert spec.task_plan_allowed is False
    properties = set(spec.input_model.model_json_schema()["properties"])
    assert properties.isdisjoint(
        {
            "user_id",
            "thread_id",
            "run_id",
            "provider",
            "action_id",
            "next_actions",
        }
    )

    output = ControllerOutput(
        mode="capability_proposals",
        tool_calls=[
            ControllerToolCall(
                call_id="research",
                name="research_start",
                arguments={
                    "objective": "搜索最新的好评图书",
                    "mode": "deep_research",
                    "subquestions": ["近期有哪些获得可靠好评的图书？"],
                    "constraints": ["只使用可引用公开来源"],
                    "max_sources": 6,
                    "max_rounds": 2,
                    "language": "zh-CN",
                },
            )
        ],
    )
    batch = ProposalValidator(registry).validate(output)
    plan = PlanGraphNormalizer().normalize(
        WorkflowCompiler().compile(
            batch,
            goal="深度搜索下最新的好评图书",
        )
    )
    assert [item.operation for item in plan.actions] == list(
        RESEARCH_STAGE_OPERATIONS
    )
    for index, action in enumerate(plan.actions):
        assert action.depends_on == (
            [] if index == 0 else [plan.actions[index - 1].action_id]
        )

    receipt = await SystemRuntime(
        external_runtime=ExternalCapabilityRuntime(
            availability=enabled,
            adapters=[
                ResearchPrepareAdapter(),
                ResearchSearchAdapter(search_gateway=_FixtureGateway()),
                ResearchEvidenceAdmissionAdapter(),
                ResearchReportAdapter(),
            ],
        )
    ).execute(
        plan,
        context=ExecutionContext(
            user_id="00000000-0000-0000-0000-000000000001",
            thread_id="00000000-0000-0000-0000-000000000002",
            request_id="r4-research-fixture",
        ),
    )
    assert receipt.status == "completed"
    report = receipt.actions[-1].output
    serialized = json.dumps(report, ensure_ascii=False)
    assert report["result_mode"] == "research_report_evidence"
    for token in (
        "fixture-provider",
        "RAW_FIXTURE_BODY",
        "javascript:",
        "must-not-leak",
    ):
        assert token not in serialized
    print(
        json.dumps(
            {
                "case_id": "deep_book_research",
                "input": "深度搜索下最新的好评图书",
                "expected_capability": "research_start",
                "contract": "r4-research-v1",
                "operations": list(RESEARCH_STAGE_OPERATIONS),
                "continuous_dependencies": True,
                "research_state_writes": 0,
                "report_from_admitted_evidence_only": True,
                "controller_decision_source": "fixture",
                "online_model_calls": 0,
                "release_gate_credit": False,
                "status": "passed",
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
