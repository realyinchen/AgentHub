from __future__ import annotations

from collections.abc import Mapping
import time

from app.services.external_search.contracts import (
    SearchAttempt,
    SearchProvider,
    SearchRequest,
    SearchResult,
)
from app.services.external_search.policy import provider_order


class SearchGateway:
    """Try configured providers sequentially and return one domain result."""

    def __init__(
        self,
        providers: Mapping[str, SearchProvider] | None = None,
    ) -> None:
        self._providers = dict(providers) if providers is not None else None

    async def search(
        self,
        request: SearchRequest | dict,
        *,
        previously_used: tuple[str, ...] = (),
    ) -> SearchResult:
        search_request = SearchRequest.model_validate(request)
        providers = (
            self._providers
            if self._providers is not None
            else _runtime_providers()
        )
        attempts: list[SearchAttempt] = []
        empty_result: SearchResult | None = None

        for provider_name in provider_order(
            search_request,
            previously_used=previously_used,
        ):
            provider = providers.get(provider_name)
            if provider is None:
                attempts.append(
                    SearchAttempt(
                        provider=provider_name,
                        outcome="unavailable",
                        error_type="not_configured",
                        error=f"{provider_name} is not configured",
                    )
                )
                continue

            started_at = time.perf_counter()
            try:
                result = await provider.search(search_request)
            except Exception as exc:
                attempts.append(
                    SearchAttempt(
                        provider=provider_name,
                        outcome="unavailable",
                        duration_ms=int(
                            (time.perf_counter() - started_at) * 1000
                        ),
                        error_type="adapter_error",
                        error=str(exc) or exc.__class__.__name__,
                    )
                )
                continue
            result = _apply_business_filters(result, search_request)
            attempts.extend(result.attempts or [
                SearchAttempt(provider=provider_name, outcome=result.outcome)
            ])
            if result.outcome == "found":
                return result.model_copy(update={"attempts": attempts})
            if result.outcome == "empty" and empty_result is None:
                empty_result = result

        if empty_result is not None:
            return empty_result.model_copy(update={"attempts": attempts})
        return SearchResult(
            outcome="unavailable",
            query=search_request.query,
            effective_query=search_request.query,
            attempts=attempts,
            error=_combined_error(attempts),
        )


def _runtime_providers() -> dict[str, SearchProvider]:
    from app.services.external_search.providers.anysearch import AnySearchProvider
    from app.services.external_search.providers.tavily import TavilyProvider

    return {
        "tavily": TavilyProvider(),
        "anysearch": AnySearchProvider(),
    }


def _combined_error(attempts: list[SearchAttempt]) -> str:
    errors = [attempt.error for attempt in attempts if attempt.error]
    return "; ".join(dict.fromkeys(errors))[:1000]


def _apply_business_filters(
    result: SearchResult,
    request: SearchRequest,
) -> SearchResult:
    if result.outcome != "found":
        return result
    hits = result.hits
    if request.include_url_prefixes:
        hits = [
            hit
            for hit in hits
            if any(
                hit.url.startswith(prefix)
                for prefix in request.include_url_prefixes
            )
        ]
    hits = hits[: request.max_results]
    if hits:
        return result.model_copy(
            update={
                "hits": hits,
                "metadata": {
                    **result.metadata,
                    "post_filter_count": len(hits),
                },
            }
        )
    normalized_attempts = [
        attempt.model_copy(
            update={
                "outcome": "empty",
                "error_type": "filtered_empty",
                "error": "provider results did not satisfy URL filters",
            }
        )
        for attempt in result.attempts
    ]
    return result.model_copy(
        update={
            "outcome": "empty",
            "hits": [],
            "attempts": normalized_attempts,
            "error": "",
            "metadata": {
                **result.metadata,
                "post_filter_count": 0,
            },
        }
    )


def get_search_gateway() -> SearchGateway:
    return SearchGateway()
