"""Verify the R4 weather contract with no database or external provider."""

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
from app.services.external_capabilities.weather import WeatherRuntimeAdapter
from app.services.external_search.contracts import SearchHit, SearchResult


class _FixtureGateway:
    async def search(self, request):
        return SearchResult(
            outcome="found",
            provider="fixture-provider",
            query=request.query,
            hits=[
                SearchHit(
                    title="北京天气",
                    url="https://weather.example/beijing",
                    snippet="今天北京天气晴。",
                    content="RAW_FIXTURE_BODY",
                    provider="fixture-provider",
                    metadata={"secret": "not-for-receipt"},
                )
            ],
            metadata={"raw": "not-for-receipt"},
        )


async def _main() -> int:
    enabled = ExternalCapabilityAvailability(weather_get=True)
    registry = CapabilityRegistry(availability=enabled)
    schema = next(
        item
        for item in registry.tool_schemas()
        if item["function"]["name"] == "weather_get"
    )
    properties = set(schema["function"]["parameters"]["properties"])
    forbidden = {
        "user_id",
        "thread_id",
        "request_id",
        "provider",
        "api_key",
        "timezone",
    }
    assert properties == {"location", "date", "units", "language"}
    assert properties.isdisjoint(forbidden)

    output = ControllerOutput(
        mode="capability_proposals",
        tool_calls=[
            ControllerToolCall(
                call_id="weather",
                name="weather_get",
                arguments={
                    "location": "北京",
                    "date": "today",
                },
            )
        ],
    )
    batch = ProposalValidator(registry).validate(output)
    plan = WorkflowCompiler().compile(
        batch,
        goal="今天北京天气怎么样？",
    )
    assert plan.response_mode == "model"
    assert [item.operation for item in plan.actions] == ["weather_get_v1"]

    runtime = ExternalCapabilityRuntime(
        availability=enabled,
        adapters=[
            WeatherRuntimeAdapter(search_gateway=_FixtureGateway())
        ],
    )
    receipt = await SystemRuntime(
        external_runtime=runtime
    ).execute(
        plan,
        context=ExecutionContext(
            user_id="00000000-0000-0000-0000-000000000001",
            thread_id="00000000-0000-0000-0000-000000000002",
            request_id="r4-weather-fixture",
        ),
    )
    assert receipt.status == "completed"
    payload = receipt.actions[0].output
    serialized = json.dumps(payload, ensure_ascii=False)
    for token in (
        "fixture-provider",
        "RAW_FIXTURE_BODY",
        "not-for-receipt",
    ):
        assert token not in serialized
    print(
        json.dumps(
            {
                "case_id": "weather_current",
                "input": "今天北京天气怎么样？",
                "expected_capability": "weather_get",
                "contract": "r4-weather-v1",
                "schema_business_fields_only": True,
                "private_runtime_operation": "weather_get_v1",
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
