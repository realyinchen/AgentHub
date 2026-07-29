from __future__ import annotations

import json
from typing import Any

from langchain_core.tools import BaseTool, tool
from pydantic import BaseModel, Field

from app.services.external_search import SearchRequest, get_search_gateway
from app.services.tool_admission import (
    ToolPolicyDeclaration,
    get_tool_admission_gate,
)


WEB_SEARCH_TOOL_POLICY = ToolPolicyDeclaration(
    tool_name="web_search",
    required_policy_flags=["can_use_web_search"],
    side_effect_scope="external_call",
    external_call=True,
    max_calls_per_turn=3,
    blocked_status="tool_blocked",
)


class WebSearchInput(BaseModel):
    """Provider-neutral input exposed to the execution layer."""

    query: str = Field(min_length=1, max_length=300)
    max_results: int = Field(default=5, ge=1, le=10)
    detail: str = Field(default="standard", description="standard or deep")
    time_range: str | None = Field(
        default=None,
        description="day, week, month, or year",
    )
    include_domains: list[str] = Field(default_factory=list, max_length=300)
    exclude_domains: list[str] = Field(default_factory=list, max_length=150)
    include_url_prefixes: list[str] = Field(default_factory=list, max_length=20)
    language: str = ""
    zone: str | None = Field(default=None, description="cn or intl")
    category: str = Field(default="general", description="general or news")


def create_web_search() -> BaseTool:
    """Create the stable web tool backed by the provider-neutral gateway."""

    @tool(args_schema=WebSearchInput)
    async def web_search(
        query: str,
        max_results: int = 5,
        detail: str = "standard",
        time_range: str | None = None,
        include_domains: list[str] | None = None,
        exclude_domains: list[str] | None = None,
        include_url_prefixes: list[str] | None = None,
        language: str = "",
        zone: str | None = None,
        category: str = "general",
    ) -> str:
        """Search current external information through configured providers."""

        admission = get_tool_admission_gate().admit_current_turn(
            WEB_SEARCH_TOOL_POLICY
        )
        if not admission.allowed:
            return _json(
                {
                    "status": admission.blocked_status or "tool_blocked",
                    "query": query,
                    "error": admission.reason,
                    "tool_admission": admission.model_dump(mode="json"),
                }
            )

        try:
            request = SearchRequest(
                query=query,
                max_results=max_results,
                detail=detail,
                time_range=time_range,
                include_domains=include_domains or [],
                exclude_domains=exclude_domains or [],
                include_url_prefixes=include_url_prefixes or [],
                language=language,
                zone=zone,
                category=category,
            )
        except ValueError as exc:
            return _json(
                {
                    "status": "invalid_request",
                    "query": query,
                    "error": str(exc),
                }
            )

        result = await get_search_gateway().search(request)
        payload = result.model_dump(mode="json")
        payload.update(
            {
                "status": "ok" if result.outcome == "found" else "completed",
                "result": {
                    "results": [
                        hit.model_dump(mode="json")
                        for hit in result.hits
                    ]
                },
                "metadata": {
                    **result.metadata,
                    "outcome": result.outcome,
                    "attempts": [
                        attempt.model_dump(mode="json")
                        for attempt in result.attempts
                    ],
                    "writes_long_term_memory": False,
                    "writes_research_state": False,
                },
            }
        )
        return _json(payload)

    web_search.name = "web_search"
    web_search.description = (
        "Search current external information. Provide business filters such as "
        "recency or domains; provider selection and failover are handled by the "
        "search gateway."
    )
    return web_search


def _json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, default=str)
