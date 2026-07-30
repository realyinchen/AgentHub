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
from app.services.agent_runtime.contracts import ExecutionContext
from app.services.agent_runtime.runtime import SystemRuntime
from app.services.external_capabilities.availability import (
    ExternalCapabilityAvailability,
)
from app.services.external_capabilities.runtime import (
    ExternalCapabilityRuntime,
)
from app.services.external_capabilities.web import WebSearchRuntimeAdapter
from app.services.external_search.contracts import (
    SearchAttempt,
    SearchHit,
    SearchResult,
)


def _availability(*, web: bool) -> ExternalCapabilityAvailability:
    return ExternalCapabilityAvailability(web_search=web)


def _web_output() -> ControllerOutput:
    return ControllerOutput(
        mode="capability_proposals",
        tool_calls=[
            ControllerToolCall(
                call_id="web",
                name="web_search",
                arguments={
                    "query": "本周人工智能重要新闻",
                    "max_results": 4,
                    "detail": "standard",
                    "time_range": "week",
                    "language": "zh-CN",
                    "category": "news",
                },
            )
        ],
    )


def _compile_web_plan():
    registry = CapabilityRegistry(availability=_availability(web=True))
    batch = ProposalValidator(registry).validate(_web_output())
    return WorkflowCompiler().compile(
        batch,
        goal="搜索本周人工智能重要新闻。",
    )


class _WebGatewayStub:
    async def search(self, request):
        return SearchResult(
            outcome="found",
            provider="private-provider",
            query=request.query,
            effective_query=request.query,
            hits=[
                SearchHit(
                    title="AI 新闻",
                    url="https://news.example/ai",
                    snippet="本周发布了一项新的人工智能研究。",
                    content="RAW_WEB_DOCUMENT",
                    published_date="2026-07-30",
                    provider="private-provider",
                    score=0.91,
                    metadata={"raw_response": "must-not-leak"},
                )
            ],
            attempts=[
                SearchAttempt(
                    provider="private-provider",
                    outcome="found",
                    upstream_request_id="private-request-id",
                )
            ],
            metadata={"provider_dump": "must-not-leak"},
        )


class WebCapabilityContractTests(unittest.TestCase):
    def test_web_schema_is_independently_flagged_and_business_only(self):
        weather_only = CapabilityRegistry(
            availability=ExternalCapabilityAvailability(weather_get=True)
        )
        web_only = CapabilityRegistry(availability=_availability(web=True))

        self.assertNotIn("web_search", weather_only.enabled_names)
        self.assertNotIn("weather_get", web_only.enabled_names)
        self.assertIn("web_search", web_only.enabled_names)
        schema = next(
            item["function"]["parameters"]
            for item in web_only.tool_schemas()
            if item["function"]["name"] == "web_search"
        )
        properties = set(schema["properties"])
        self.assertEqual(
            properties,
            {
                "query",
                "max_results",
                "detail",
                "time_range",
                "include_domains",
                "exclude_domains",
                "language",
                "category",
            },
        )
        self.assertTrue(
            {
                "user_id",
                "thread_id",
                "provider",
                "api_key",
                "zone",
                "round_index",
            }.isdisjoint(properties)
        )

    def test_web_proposal_compiles_to_private_runtime_operation(self):
        plan = _compile_web_plan()

        self.assertEqual(plan.response_mode, "model")
        self.assertEqual([item.operation for item in plan.actions], ["web_search_v2"])
        self.assertEqual(plan.actions[0].capability, "external_search")
        self.assertNotIn("provider", plan.actions[0].arguments)


class WebCapabilityRuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def test_disabled_web_runtime_rejects_compiled_bypass(self):
        plan = _compile_web_plan()
        runtime = ExternalCapabilityRuntime(
            availability=_availability(web=False),
            adapters=[
                WebSearchRuntimeAdapter(search_gateway=_WebGatewayStub())
            ],
        )

        receipt = await SystemRuntime(
            external_runtime=runtime
        ).execute(
            plan,
            context=ExecutionContext(
                user_id=uuid4(),
                thread_id=uuid4(),
                request_id="r4-web-disabled",
            ),
        )

        self.assertEqual(receipt.status, "blocked")
        self.assertFalse(receipt.actions[0].admitted)
        self.assertEqual(
            receipt.actions[0].error,
            "external_capability_disabled:web_search",
        )

    async def test_web_receipt_is_bounded_citation_evidence(self):
        plan = _compile_web_plan()
        runtime = ExternalCapabilityRuntime(
            availability=_availability(web=True),
            adapters=[
                WebSearchRuntimeAdapter(search_gateway=_WebGatewayStub())
            ],
        )

        receipt = await SystemRuntime(
            external_runtime=runtime
        ).execute(
            plan,
            context=ExecutionContext(
                user_id=uuid4(),
                thread_id=uuid4(),
                request_id="r4-web-success",
            ),
        )

        self.assertEqual(receipt.status, "completed")
        output = receipt.actions[0].output
        self.assertEqual(output["result_mode"], "web_evidence")
        self.assertEqual(output["status"], "ok")
        self.assertEqual(output["query"], "本周人工智能重要新闻")
        self.assertEqual(len(output["sources"]), 1)
        serialized = str(output)
        for forbidden in (
            "private-provider",
            "RAW_WEB_DOCUMENT",
            "raw_response",
            "private-request-id",
            "provider_dump",
        ):
            self.assertNotIn(forbidden, serialized)


if __name__ == "__main__":
    unittest.main()
