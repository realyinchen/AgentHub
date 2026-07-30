from __future__ import annotations

from typing import Any, Protocol

from app.services.agent_runtime.contracts import (
    ActionReceipt,
    ExecutionContext,
)
from app.services.external_capabilities.book_sanitizer import (
    BookSearchReceiptSanitizer,
)
from app.services.external_capabilities.contracts import BookSearchInput
from app.services.external_search.contracts import SearchRequest, SearchResult


class BookSearchGateway(Protocol):
    async def search(self, request: SearchRequest) -> SearchResult:
        ...


class BookSearchRuntimeAdapter:
    """Search public book evidence without cache or user-state writes."""

    operation = "book_search_v1"

    def __init__(
        self,
        *,
        search_gateway: BookSearchGateway | None = None,
        sanitizer: BookSearchReceiptSanitizer | None = None,
    ) -> None:
        if search_gateway is None:
            from app.services.external_search import get_search_gateway

            search_gateway = get_search_gateway()
        self._search_gateway = search_gateway
        self._sanitizer = sanitizer or BookSearchReceiptSanitizer()

    async def execute(
        self,
        arguments: dict[str, Any],
        *,
        context: ExecutionContext,
        previous: list[ActionReceipt],
    ) -> dict[str, Any]:
        del context, previous
        request = BookSearchInput.model_validate(arguments)
        result = await self._search_gateway.search(
            SearchRequest(
                query=_book_query(request),
                max_results=request.limit,
                detail="standard",
                language=request.language,
                zone=(
                    "cn"
                    if request.language.lower().startswith("zh")
                    else None
                ),
                category="general",
            )
        )
        return self._sanitizer.sanitize(
            request,
            result,
        ).model_dump(mode="json")


def _book_query(request: BookSearchInput) -> str:
    constraints: list[str] = []
    if request.genres:
        constraints.append("类型 " + " ".join(request.genres))
    if request.authors:
        constraints.append("作者 " + " ".join(request.authors))
    if request.audience:
        constraints.append("适读 " + request.audience)
    if request.publication_year_from is not None:
        constraints.append(f"{request.publication_year_from}年以后")
    if request.publication_year_to is not None:
        constraints.append(f"{request.publication_year_to}年以前")
    suffix = " ".join(constraints)
    return " ".join(
        part
        for part in (
            request.query,
            suffix,
            "图书 书籍 作者 出版社 ISBN",
        )
        if part
    )


__all__ = ["BookSearchGateway", "BookSearchRuntimeAdapter"]

