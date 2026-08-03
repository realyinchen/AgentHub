"""Verify the R4 web contract with no database or external provider."""

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
from app.services.agent_core.proposal_validator import ProposalValidator
from app.services.agent_runtime.contracts import ExecutionContext
from app.services.agent_runtime.runtime import SystemRuntime
from app.services.external_capabilities.availability import (
    ExternalCapabilityAvailability,
)
from app.services.external_capabilities.runtime import (
    ExternalCapabilityRuntime,
)
from app.services.external_capabilities.web import WebSearchRuntimeAdapter
from app.services.external_search.contracts import SearchHit, SearchResult


class _FixtureGateway:
    async def search(self, request):
        return SearchResult(
            outcome="found",
            provider="fixture-provider",
            query=request.query,
            hits=[
                SearchHit(
                    title="法国总统官方资料",
                    url="https://government.example/france-president",
                    snippet="法国总统的当前公开资料。",
                    content="RAW_FIXTURE_BODY",
                    provider="fixture-provider",
                    metadata={"secret": "not-for-receipt"},
                )
            ],
            metadata={"raw": "not-for-receipt"},
        )


async def _main() -> int:
    enabled = ExternalCapabilityAvailability(web_search=True)
    registry = CapabilityRegistry(availability=enabled)
    schema = next(
        item
        for item in registry.tool_schemas()
        if item["function"]["name"] == "web_search"
    )
    properties = set(schema["function"]["parameters"]["properties"])
    assert properties == {
        "query",
        "max_results",
        "detail",
        "time_range",
        "include_domains",
        "exclude_domains",
        "language",
        "category",
    }
    assert properties.isdisjoint(
        {
            "user_id",
            "thread_id",
            "request_id",
            "provider",
            "api_key",
            "zone",
            "round_index",
        }
    )

    output = ControllerOutput(
        mode="capability_proposals",
        tool_calls=[
            ControllerToolCall(
                call_id="web",
                name="web_search",
                arguments={
                    "query": "法国总统是谁",
                    "time_range": "month",
                    "language": "zh-CN",
                    "category": "news",
                },
            )
        ],
    )
    batch = ProposalValidator(registry).validate(output)
    plan = WorkflowCompiler().compile(
        batch,
        goal="法国总统是谁？",
    )
    assert plan.response_mode == "model"
    assert [item.operation for item in plan.actions] == ["web_search_v2"]

    receipt = await SystemRuntime(
        external_runtime=ExternalCapabilityRuntime(
            availability=enabled,
            adapters=[
                WebSearchRuntimeAdapter(search_gateway=_FixtureGateway())
            ],
        )
    ).execute(
        plan,
        context=ExecutionContext(
            user_id="00000000-0000-0000-0000-000000000001",
            thread_id="00000000-0000-0000-0000-000000000002",
            request_id="r4-web-fixture",
        ),
    )
    assert receipt.status == "completed"
    serialized = json.dumps(receipt.actions[0].output, ensure_ascii=False)
    for token in (
        "fixture-provider",
        "RAW_FIXTURE_BODY",
        "not-for-receipt",
    ):
        assert token not in serialized
    print(
        json.dumps(
            {
                "case_id": "external_current_fact",
                "input": "法国总统是谁？",
                "expected_capability": "web_search",
                "contract": "r4-web-v1",
                "schema_business_fields_only": True,
                "private_runtime_operation": "web_search_v2",
                "runtime_flag_admission": True,
                "receipt_sanitized": True,
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
