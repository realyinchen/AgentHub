from __future__ import annotations

import unittest

from app.services.external_search import (
    SearchAttempt,
    SearchGateway,
    SearchHit,
    SearchRequest,
    SearchResult,
)
from app.services.external_search.policy import provider_order
from app.services.research.loop.contracts import ResearchSearchTask
from app.services.research.loop.source_projection import (
    project_research_search_output,
)
from app.services.research.search_policy import build_research_search_request
from app.services.provider_config import (
    get_provider_registry,
    reset_provider_registry,
)


class _FakeProvider:
    def __init__(
        self,
        name: str,
        outcome: str,
        *,
        url: str = "",
    ) -> None:
        self.name = name
        self.outcome = outcome
        self.url = url or f"https://{name}.example/result"
        self.calls = 0

    async def search(self, request: SearchRequest) -> SearchResult:
        self.calls += 1
        hits = (
            [
                SearchHit(
                    title=f"{self.name} result",
                    url=self.url,
                    snippet="A source-backed result.",
                    provider=self.name,
                )
            ]
            if self.outcome == "found"
            else []
        )
        return SearchResult(
            outcome=self.outcome,
            provider=self.name,
            query=request.query,
            effective_query=request.query,
            hits=hits,
            error=(
                f"{self.name} unavailable"
                if self.outcome == "unavailable"
                else ""
            ),
            attempts=[
                SearchAttempt(
                    provider=self.name,
                    outcome=self.outcome,
                    error=(
                        f"{self.name} unavailable"
                        if self.outcome == "unavailable"
                        else ""
                    ),
                )
            ],
        )


class _RaisingProvider:
    def __init__(self, name: str) -> None:
        self.name = name

    async def search(self, request: SearchRequest) -> SearchResult:
        del request
        raise RuntimeError(f"{self.name} exploded")


class SearchPolicyTests(unittest.TestCase):
    def test_default_registry_exposes_anonymous_anysearch(self) -> None:
        reset_provider_registry()
        providers = get_provider_registry().list_configs().providers
        anysearch = next(
            item for item in providers if item.provider_key == "anysearch"
        )
        self.assertTrue(anysearch.enabled)
        self.assertEqual(anysearch.provider_type, "web_search")
        self.assertIn("web_search", anysearch.capabilities)
        self.assertTrue(anysearch.settings["allow_anonymous"])
        self.assertNotEqual(
            anysearch.health.status,
            "missing_credentials",
        )

    def test_douban_book_constraint_targets_entity_pages(self) -> None:
        request = build_research_search_request(
            "豆瓣好评图书，给我5本好书推荐",
            constraints=[
                {
                    "field": "source_domain",
                    "operator": "in",
                    "value": ["book.douban.com"],
                },
                {"field": "rating", "operator": "gte", "value": "好评"},
                {"field": "result_limit", "operator": "equals", "value": 5},
            ],
        )
        self.assertEqual(request.include_domains, ["book.douban.com"])
        self.assertIn("site:book.douban.com/subject/", request.query)
        self.assertEqual(
            request.include_url_prefixes,
            ["https://book.douban.com/subject/"],
        )
        self.assertIn("review", request.requirements)
        self.assertIn("result_limit", request.requirements)
        self.assertEqual(request.max_results, 5)

    def test_chinese_general_query_prefers_anysearch(self) -> None:
        request = SearchRequest(query="今天有什么新闻")
        self.assertEqual(provider_order(request), ("anysearch", "tavily"))

    def test_explicit_domain_prefers_tavily_for_non_chinese_query(self) -> None:
        request = SearchRequest(
            query="well reviewed books",
            include_domains=["example.test"],
        )
        self.assertEqual(provider_order(request), ("tavily", "anysearch"))

    def test_chinese_domain_query_still_prefers_anysearch(self) -> None:
        request = SearchRequest(
            query="豆瓣好评图书",
            include_domains=["book.douban.com"],
        )
        self.assertEqual(provider_order(request), ("anysearch", "tavily"))

    def test_next_round_moves_used_provider_to_end(self) -> None:
        request = SearchRequest(query="中文图书")
        self.assertEqual(
            provider_order(request, previously_used=("anysearch",)),
            ("tavily", "anysearch"),
        )


class SearchGatewayTests(unittest.IsolatedAsyncioTestCase):
    async def test_tavily_failure_falls_back_to_anysearch(self) -> None:
        tavily = _FakeProvider("tavily", "unavailable")
        anysearch = _FakeProvider("anysearch", "found")
        gateway = SearchGateway(
            {"tavily": tavily, "anysearch": anysearch}
        )
        result = await gateway.search(
            SearchRequest(
                query="well reviewed books",
                include_domains=["example.test"],
            )
        )
        self.assertEqual(result.outcome, "found")
        self.assertEqual(result.provider, "anysearch")
        self.assertEqual(
            [attempt.provider for attempt in result.attempts],
            ["tavily", "anysearch"],
        )
        self.assertEqual(tavily.calls, 1)
        self.assertEqual(anysearch.calls, 1)

    async def test_anysearch_failure_falls_back_to_tavily(self) -> None:
        tavily = _FakeProvider("tavily", "found")
        anysearch = _FakeProvider("anysearch", "unavailable")
        gateway = SearchGateway(
            {"tavily": tavily, "anysearch": anysearch}
        )
        result = await gateway.search(SearchRequest(query="中文图书推荐"))
        self.assertEqual(result.outcome, "found")
        self.assertEqual(result.provider, "tavily")
        self.assertEqual(
            [attempt.provider for attempt in result.attempts],
            ["anysearch", "tavily"],
        )

    async def test_adapter_exception_does_not_break_failover(self) -> None:
        gateway = SearchGateway(
            {
                "tavily": _RaisingProvider("tavily"),
                "anysearch": _FakeProvider("anysearch", "found"),
            }
        )
        result = await gateway.search(
            SearchRequest(
                query="site result",
                include_domains=["example.test"],
            )
        )
        self.assertEqual(result.outcome, "found")
        self.assertEqual(result.provider, "anysearch")
        self.assertEqual(result.attempts[0].error_type, "adapter_error")

    async def test_url_filter_can_fall_back_to_next_provider(self) -> None:
        gateway = SearchGateway(
            {
                "tavily": _FakeProvider(
                    "tavily",
                    "found",
                    url="https://example.test/chart",
                ),
                "anysearch": _FakeProvider(
                    "anysearch",
                    "found",
                    url="https://example.test/subject/42",
                ),
            }
        )
        result = await gateway.search(
            SearchRequest(
                query="books",
                include_domains=["example.test"],
                include_url_prefixes=["https://example.test/subject/"],
            )
        )
        self.assertEqual(result.provider, "anysearch")
        self.assertEqual(result.outcome, "found")
        self.assertEqual(result.attempts[0].error_type, "filtered_empty")

    async def test_both_unavailable_is_completed_domain_outcome(self) -> None:
        gateway = SearchGateway(
            {
                "tavily": _FakeProvider("tavily", "unavailable"),
                "anysearch": _FakeProvider("anysearch", "unavailable"),
            }
        )
        result = await gateway.search(
            SearchRequest(
                query="豆瓣好评图书",
                include_domains=["book.douban.com"],
            )
        )
        self.assertEqual(result.execution_status, "completed")
        self.assertEqual(result.outcome, "unavailable")
        self.assertEqual(len(result.attempts), 2)

        projected = project_research_search_output(
            task=ResearchSearchTask(
                round_index=1,
                objective="豆瓣好评图书",
                query="豆瓣好评图书",
                include_domains=["book.douban.com"],
            ),
            provider_output=result.model_dump(mode="json"),
        )
        self.assertEqual(projected.status, "completed")
        self.assertEqual(projected.provider_status, "unavailable")
        self.assertEqual(projected.source_count, 0)

    async def test_empty_is_distinct_from_unavailable(self) -> None:
        gateway = SearchGateway(
            {
                "tavily": _FakeProvider("tavily", "empty"),
                "anysearch": _FakeProvider("anysearch", "unavailable"),
            }
        )
        result = await gateway.search(
            SearchRequest(query="rare", include_domains=["example.test"])
        )
        self.assertEqual(result.outcome, "empty")
        self.assertEqual(result.execution_status, "completed")


if __name__ == "__main__":
    unittest.main()
