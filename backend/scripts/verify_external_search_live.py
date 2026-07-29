"""Live smoke check for the configured external-search gateway."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from urllib.parse import urlparse


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.infra.database import dispose_database, init_database
from app.services.external_search import SearchRequest, get_search_gateway
from app.services.research.loop.contracts import ResearchSearchTask
from app.services.research.loop.source_projection import (
    project_research_search_output,
)
from app.services.research.search_policy import build_research_search_request


async def _run() -> None:
    await init_database()
    try:
        policy_request = build_research_search_request(
            "豆瓣好评图书，给我5本好书推荐。",
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
        result = await get_search_gateway().search(
            SearchRequest.model_validate(
                {
                    **policy_request.tool_arguments(),
                    "zone": "cn",
                }
            )
        )
        if result.outcome != "found":
            raise AssertionError(result.model_dump(mode="json"))
        if len(result.hits) != 5:
            raise AssertionError(f"expected 5 hits, got {len(result.hits)}")
        hosts = [urlparse(hit.url).netloc for hit in result.hits]
        if not all(host.endswith("douban.com") for host in hosts):
            raise AssertionError(hosts)
        paths = [urlparse(hit.url).path for hit in result.hits]
        if not all(path.startswith("/subject/") for path in paths):
            raise AssertionError(paths)
        readable_titles = " ".join(hit.title for hit in result.hits)
        if "豆瓣" not in readable_titles:
            raise AssertionError(
                f"provider returned unreadable or irrelevant titles: {readable_titles}"
            )
        projected = project_research_search_output(
            task=ResearchSearchTask(
                round_index=1,
                objective=policy_request.objective,
                **policy_request.tool_arguments(),
            ),
            provider_output=result.model_dump(mode="json"),
        )
        if projected.publishable_source_count != 5:
            raise AssertionError(
                projected.model_dump(mode="json")
            )
        print(
            {
                "outcome": result.outcome,
                "provider": result.provider,
                "attempts": [
                    (item.provider, item.outcome, item.error_type)
                    for item in result.attempts
                ],
                "result_count": len(result.hits),
                "titles": [item.title[:60] for item in result.hits],
                "hosts": hosts,
                "paths": paths,
                "publishable_source_count": (
                    projected.publishable_source_count
                ),
            }
        )
    finally:
        await dispose_database()


if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(_run())
