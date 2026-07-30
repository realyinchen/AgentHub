from __future__ import annotations

import asyncio
import unittest
from uuid import uuid4

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
from app.services.external_capabilities.policy import (
    CapabilityRuntimePolicy,
    ExternalCapabilityPolicyRegistry,
)
from app.services.external_capabilities.runtime import (
    ExternalCapabilityRuntime,
)
from app.services.external_capabilities.weather import WeatherRuntimeAdapter
from app.services.external_search.contracts import (
    SearchAttempt,
    SearchHit,
    SearchResult,
)
from scripts.verify_r4_weather_live import _failure_code


def _availability(*, weather: bool) -> ExternalCapabilityAvailability:
    return ExternalCapabilityAvailability(weather_get=weather)


def _weather_output() -> ControllerOutput:
    return ControllerOutput(
        mode="capability_proposals",
        tool_calls=[
            ControllerToolCall(
                call_id="weather",
                name="weather_get",
                arguments={
                    "location": "杭州",
                    "date": "tomorrow",
                    "units": "metric",
                    "language": "zh-CN",
                },
            )
        ],
    )


def _compile_weather_plan():
    registry = CapabilityRegistry(availability=_availability(weather=True))
    batch = ProposalValidator(registry).validate(_weather_output())
    return WorkflowCompiler().compile(batch, goal="杭州明天天气怎么样？")


class _SearchGatewayStub:
    async def search(self, request):
        return SearchResult(
            outcome="found",
            provider="secret-provider",
            query=request.query,
            effective_query=request.query,
            hits=[
                SearchHit(
                    title="杭州天气",
                    url="https://weather.example/hangzhou",
                    snippet="明天多云，气温 20 至 27 摄氏度。",
                    content="RAW_PROVIDER_DUMP",
                    published_date="2026-07-30",
                    provider="secret-provider",
                    metadata={"upstream_secret": "must-not-leak"},
                )
            ],
            attempts=[
                SearchAttempt(
                    provider="secret-provider",
                    outcome="found",
                    error="internal-attempt-detail",
                )
            ],
            metadata={"provider_payload": "must-not-leak"},
        )


class _SlowSearchGatewayStub:
    async def search(self, request):
        await asyncio.sleep(0.05)
        raise AssertionError("timeout should cancel this adapter")


class WeatherCapabilityContractTests(unittest.TestCase):
    def test_weather_schema_is_flagged_and_contains_only_business_fields(self):
        disabled = CapabilityRegistry(
            availability=_availability(weather=False)
        )
        enabled = CapabilityRegistry(
            availability=_availability(weather=True)
        )

        self.assertNotIn("weather_get", disabled.enabled_names)
        self.assertIn("weather_get", enabled.enabled_names)
        schema = next(
            item["function"]["parameters"]
            for item in enabled.tool_schemas()
            if item["function"]["name"] == "weather_get"
        )
        properties = set(schema["properties"])
        self.assertEqual(
            properties,
            {"location", "date", "units", "language"},
        )
        self.assertTrue(
            {
                "user_id",
                "thread_id",
                "request_id",
                "provider",
                "api_key",
                "timezone",
            }.isdisjoint(properties)
        )

    def test_weather_proposal_compiles_to_private_runtime_operation(self):
        plan = _compile_weather_plan()

        self.assertEqual(plan.response_mode, "model")
        self.assertEqual(len(plan.actions), 1)
        action = plan.actions[0]
        self.assertEqual(action.capability, "weather")
        self.assertEqual(action.operation, "weather_get_v1")
        self.assertEqual(action.arguments["location"], "杭州")
        self.assertNotIn("user_id", action.arguments)
        self.assertNotIn("provider", action.arguments)

    def test_live_canary_failure_codes_never_copy_provider_error(self):
        RateLimitError = type("RateLimitError", (Exception,), {})
        self.assertEqual(
            _failure_code(RateLimitError("sensitive upstream quota detail")),
            "model_provider_capacity",
        )
        self.assertEqual(
            _failure_code(TimeoutError("sensitive timeout detail")),
            "model_provider_timeout",
        )


class WeatherCapabilityRuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def test_disabled_runtime_rejects_compiled_bypass(self):
        plan = _compile_weather_plan()
        runtime = ExternalCapabilityRuntime(
            availability=_availability(weather=False),
            adapters=[
                WeatherRuntimeAdapter(search_gateway=_SearchGatewayStub())
            ],
        )

        receipt = await SystemRuntime(
            external_runtime=runtime
        ).execute(
            plan,
            context=ExecutionContext(
                user_id=uuid4(),
                thread_id=uuid4(),
                request_id="r4-weather-disabled",
            ),
        )

        self.assertEqual(receipt.status, "blocked")
        self.assertFalse(receipt.actions[0].admitted)
        self.assertEqual(
            receipt.actions[0].error,
            "external_capability_disabled:weather_get",
        )

    async def test_weather_receipt_contains_only_sanitized_evidence(self):
        plan = _compile_weather_plan()
        runtime = ExternalCapabilityRuntime(
            availability=_availability(weather=True),
            adapters=[
                WeatherRuntimeAdapter(search_gateway=_SearchGatewayStub())
            ],
        )

        receipt = await SystemRuntime(
            external_runtime=runtime
        ).execute(
            plan,
            context=ExecutionContext(
                user_id=uuid4(),
                thread_id=uuid4(),
                request_id="r4-weather-success",
                timezone="Asia/Shanghai",
            ),
        )

        self.assertEqual(receipt.status, "completed")
        output = receipt.actions[0].output
        self.assertEqual(output["result_mode"], "weather_evidence")
        self.assertEqual(output["status"], "ok")
        self.assertEqual(output["location"], "杭州")
        self.assertEqual(len(output["sources"]), 1)
        serialized = str(output)
        for forbidden in (
            "secret-provider",
            "RAW_PROVIDER_DUMP",
            "upstream_secret",
            "internal-attempt-detail",
            "provider_payload",
        ):
            self.assertNotIn(forbidden, serialized)

    async def test_weather_timeout_is_bounded_and_sanitized(self):
        plan = _compile_weather_plan()
        policies = ExternalCapabilityPolicyRegistry(
            policies={
                "weather_get_v1": CapabilityRuntimePolicy(
                    timeout_seconds=0.01,
                    max_attempts=1,
                )
            }
        )
        runtime = ExternalCapabilityRuntime(
            availability=_availability(weather=True),
            adapters=[
                WeatherRuntimeAdapter(
                    search_gateway=_SlowSearchGatewayStub()
                )
            ],
            policies=policies,
        )

        receipt = await SystemRuntime(
            external_runtime=runtime
        ).execute(
            plan,
            context=ExecutionContext(
                user_id=uuid4(),
                thread_id=uuid4(),
                request_id="r4-weather-timeout",
            ),
        )

        self.assertEqual(receipt.status, "failed")
        self.assertEqual(
            receipt.actions[0].error,
            "external_capability_timeout",
        )
        self.assertNotIn("AssertionError", str(receipt.actions[0].output))


if __name__ == "__main__":
    unittest.main()
