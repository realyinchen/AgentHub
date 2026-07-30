from __future__ import annotations

from typing import Any, Protocol

from app.services.agent_runtime.contracts import (
    ActionReceipt,
    ExecutionContext,
)
from app.services.external_capabilities.contracts import WeatherGetInput
from app.services.external_capabilities.weather_sanitizer import (
    WeatherReceiptSanitizer,
)
from app.services.external_search.contracts import SearchRequest, SearchResult


class WeatherSearchGateway(Protocol):
    async def search(self, request: SearchRequest) -> SearchResult:
        ...


class WeatherRuntimeAdapter:
    """Translate one weather business request into provider-neutral search."""

    operation = "weather_get_v1"

    def __init__(
        self,
        *,
        search_gateway: WeatherSearchGateway | None = None,
        sanitizer: WeatherReceiptSanitizer | None = None,
    ) -> None:
        if search_gateway is None:
            from app.services.external_search import get_search_gateway

            search_gateway = get_search_gateway()
        self._search_gateway = search_gateway
        self._sanitizer = sanitizer or WeatherReceiptSanitizer()

    async def execute(
        self,
        arguments: dict[str, Any],
        *,
        context: ExecutionContext,
        previous: list[ActionReceipt],
    ) -> dict[str, Any]:
        del previous
        request = WeatherGetInput.model_validate(arguments)
        search_request = SearchRequest(
            query=_weather_query(request, timezone=context.timezone),
            max_results=3,
            detail="standard",
            language=request.language,
            zone=(
                "cn"
                if request.language.lower().startswith("zh")
                else "intl"
            ),
        )
        result = await self._search_gateway.search(search_request)
        return self._sanitizer.sanitize(
            request,
            result,
        ).model_dump(mode="json")


def _weather_query(request: WeatherGetInput, *, timezone: str) -> str:
    if request.language.lower().startswith("zh"):
        return (
            f"{request.location} {request.date} 天气预报 温度 降水 风 "
            f"时区 {timezone}"
        )
    return (
        f"{request.location} {request.date} weather forecast temperature "
        f"precipitation wind timezone {timezone}"
    )


__all__ = ["WeatherRuntimeAdapter", "WeatherSearchGateway"]

