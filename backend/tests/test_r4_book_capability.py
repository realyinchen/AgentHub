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
from app.services.external_capabilities.book import BookSearchRuntimeAdapter
from app.services.external_capabilities.runtime import (
    ExternalCapabilityRuntime,
)
from app.services.external_search.contracts import SearchHit, SearchResult


def _availability(*, book: bool) -> ExternalCapabilityAvailability:
    return ExternalCapabilityAvailability(book_search=book)


def _book_output() -> ControllerOutput:
    return ControllerOutput(
        mode="capability_proposals",
        tool_calls=[
            ControllerToolCall(
                call_id="books",
                name="book_search",
                arguments={
                    "query": "适合八岁孩子的中文气象科普书",
                    "limit": 5,
                    "language": "zh-CN",
                    "genres": ["科普"],
                    "audience": "8岁儿童",
                    "publication_year_from": 2020,
                },
            )
        ],
    )


def _compile_book_plan():
    registry = CapabilityRegistry(availability=_availability(book=True))
    batch = ProposalValidator(registry).validate(_book_output())
    return WorkflowCompiler().compile(
        batch,
        goal="推荐适合八岁孩子的中文气象科普书。",
    )


class _BookGatewayStub:
    async def search(self, request):
        return SearchResult(
            outcome="found",
            provider="private-book-provider",
            query=request.query,
            effective_query=request.query,
            hits=[
                SearchHit(
                    title="《天气之书》",
                    url="https://books.example/weather",
                    snippet="作者：示例作者；适合儿童阅读。",
                    content="RAW_BOOK_PAGE",
                    provider="private-book-provider",
                    metadata={"cache_write": "must-not-happen"},
                )
            ],
            metadata={"provider_dump": "must-not-leak"},
        )


class BookCapabilityContractTests(unittest.TestCase):
    def test_book_schema_is_read_only_business_input(self):
        registry = CapabilityRegistry(
            availability=_availability(book=True)
        )
        schema = next(
            item["function"]["parameters"]
            for item in registry.tool_schemas()
            if item["function"]["name"] == "book_search"
        )
        properties = set(schema["properties"])
        self.assertEqual(
            properties,
            {
                "query",
                "limit",
                "language",
                "genres",
                "authors",
                "audience",
                "publication_year_from",
                "publication_year_to",
            },
        )
        self.assertTrue(
            {
                "user_id",
                "thread_id",
                "provider",
                "allow_additional_search",
                "cache",
                "book_id",
            }.isdisjoint(properties)
        )
        self.assertFalse(registry.get("book_search").side_effect)

    def test_book_proposal_compiles_to_private_read_operation(self):
        plan = _compile_book_plan()

        self.assertEqual(plan.response_mode, "model")
        self.assertEqual([item.operation for item in plan.actions], ["book_search_v1"])
        self.assertEqual(plan.actions[0].capability, "books")
        self.assertNotIn("user_id", plan.actions[0].arguments)


class BookCapabilityRuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def test_disabled_book_runtime_rejects_compiled_bypass(self):
        plan = _compile_book_plan()
        runtime = ExternalCapabilityRuntime(
            availability=_availability(book=False),
            adapters=[
                BookSearchRuntimeAdapter(search_gateway=_BookGatewayStub())
            ],
        )

        receipt = await SystemRuntime(
            external_runtime=runtime
        ).execute(
            plan,
            context=ExecutionContext(
                user_id=uuid4(),
                thread_id=uuid4(),
                request_id="r4-book-disabled",
            ),
        )

        self.assertEqual(receipt.status, "blocked")
        self.assertFalse(receipt.actions[0].admitted)
        self.assertEqual(
            receipt.actions[0].error,
            "external_capability_disabled:book_search",
        )

    async def test_book_receipt_has_candidates_without_cache_or_raw_dump(self):
        plan = _compile_book_plan()
        runtime = ExternalCapabilityRuntime(
            availability=_availability(book=True),
            adapters=[
                BookSearchRuntimeAdapter(search_gateway=_BookGatewayStub())
            ],
        )

        receipt = await SystemRuntime(
            external_runtime=runtime
        ).execute(
            plan,
            context=ExecutionContext(
                user_id=uuid4(),
                thread_id=uuid4(),
                request_id="r4-book-success",
            ),
        )

        self.assertEqual(receipt.status, "completed")
        output = receipt.actions[0].output
        self.assertEqual(output["result_mode"], "book_evidence")
        self.assertEqual(output["status"], "ok")
        self.assertEqual(len(output["sources"]), 1)
        serialized = str(output)
        for forbidden in (
            "private-book-provider",
            "RAW_BOOK_PAGE",
            "cache_write",
            "provider_dump",
        ):
            self.assertNotIn(forbidden, serialized)


if __name__ == "__main__":
    unittest.main()
