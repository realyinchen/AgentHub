from __future__ import annotations

from typing import Any, Protocol

from app.services.agent_runtime.contracts import (
    ActionReceipt,
    ExecutionContext,
)
from app.services.external_capabilities.contracts import WebSearchInput
from app.services.external_capabilities.web_sanitizer import (
    WebSearchReceiptSanitizer,
)
from app.services.external_search.contracts import SearchRequest, SearchResult


class WebSearchGateway(Protocol):
    async def search(self, request: SearchRequest) -> SearchResult:
        ...


class WebSearchRuntimeAdapter:
    """Translate one Controller web proposal into the shared SearchGateway."""

    operation = "web_search_v2"

    def __init__(
        self,
        *,
        search_gateway: WebSearchGateway | None = None,
        sanitizer: WebSearchReceiptSanitizer | None = None,
    ) -> None:
        if search_gateway is None:
            from app.services.external_search import get_search_gateway

            search_gateway = get_search_gateway()
        self._search_gateway = search_gateway
        self._sanitizer = sanitizer or WebSearchReceiptSanitizer()

    async def execute(
        self,
        arguments: dict[str, Any],
        *,
        context: ExecutionContext,
        previous: list[ActionReceipt],
    ) -> dict[str, Any]:
        del context, previous
        request = WebSearchInput.model_validate(arguments)
        result = await self._search_gateway.search(
            SearchRequest(
                query=request.query,
                max_results=request.max_results,
                detail=request.detail,
                time_range=request.time_range,
                include_domains=request.include_domains,
                exclude_domains=request.exclude_domains,
                language=request.language,
                zone=(
                    "cn"
                    if request.language.lower().startswith("zh")
                    else None
                ),
                category=request.category,
            )
        )
        return self._sanitizer.sanitize(
            request,
            result,
        ).model_dump(mode="json")


__all__ = ["WebSearchGateway", "WebSearchRuntimeAdapter"]

