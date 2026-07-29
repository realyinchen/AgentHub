from __future__ import annotations

import json
import time
from asyncio import to_thread
from typing import Any

import requests

from app.services.external_search.contracts import (
    SearchAttempt,
    SearchHit,
    SearchRequest,
    SearchResult,
)
from app.services.external_search.runtime_config import resolve_search_provider


class TavilyProvider:
    name = "tavily"

    async def search(self, request: SearchRequest) -> SearchResult:
        start = time.perf_counter()
        config = await resolve_search_provider(
            self.name,
            env_setting="TAVILY_API_KEY",
            default_api_base_url="https://api.tavily.com",
        )
        if not config.enabled or not config.api_key:
            return _unavailable(
                request,
                start,
                "missing_credentials",
                config.error or "Tavily credentials are not configured",
            )

        timeout_seconds = _bounded_int(
            config.settings.get("timeout_seconds"),
            30,
            3,
            60,
        )
        effective_query = _effective_query(request)
        try:
            payload = await run_tavily_search_request(
                api_key=config.api_key,
                api_base_url=config.api_base_url,
                query=effective_query,
                max_results=_provider_result_limit(request),
                search_depth="advanced" if request.detail == "deep" else "basic",
                include_answer=False,
                include_raw_content=request.detail == "deep",
                timeout_seconds=timeout_seconds,
                topic=request.category,
                time_range=request.time_range,
                include_domains=request.include_domains,
                exclude_domains=request.exclude_domains,
            )
        except Exception as exc:
            message = _redact(str(exc) or exc.__class__.__name__, config.api_key)
            return _unavailable(
                request,
                start,
                _error_type(message),
                message,
            )

        hits = [
            SearchHit(
                title=str(item.get("title") or ""),
                url=str(item.get("url") or ""),
                snippet=str(item.get("content") or ""),
                content=str(item.get("raw_content") or item.get("content") or ""),
                published_date=str(item.get("published_date") or ""),
                provider=self.name,
                score=(
                    float(item["score"])
                    if isinstance(item.get("score"), (int, float))
                    else None
                ),
                metadata={"favicon": item.get("favicon")},
            )
            for item in payload.get("results") or []
            if isinstance(item, dict) and item.get("url")
        ]
        duration_ms = int((time.perf_counter() - start) * 1000)
        outcome = "found" if hits else "empty"
        return SearchResult(
            outcome=outcome,
            provider=self.name,
            query=request.query,
            effective_query=str(payload.get("query") or effective_query),
            hits=hits,
            attempts=[
                SearchAttempt(
                    provider=self.name,
                    outcome=outcome,
                    duration_ms=duration_ms,
                    upstream_request_id=str(payload.get("request_id") or ""),
                )
            ],
            metadata={
                "response_time": payload.get("response_time"),
                "usage": payload.get("usage") or {},
            },
        )


async def run_tavily_search_request(
    *,
    api_key: str,
    query: str,
    max_results: int,
    search_depth: str,
    include_answer: bool,
    include_raw_content: bool,
    timeout_seconds: int = 30,
    api_base_url: str = "",
    topic: str = "general",
    time_range: str | None = None,
    include_domains: list[str] | None = None,
    exclude_domains: list[str] | None = None,
) -> dict[str, Any]:
    """Tavily transport used by both the adapter and provider health check."""

    payload = {
        "query": query,
        "max_results": max_results,
        "search_depth": search_depth,
        "include_answer": include_answer,
        "include_raw_content": include_raw_content,
        "topic": topic,
        "time_range": time_range,
        "include_domains": include_domains or None,
        "exclude_domains": exclude_domains or None,
    }
    body = {key: value for key, value in payload.items() if value is not None}
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "X-Client-Source": "test01-book-assistant",
    }
    base_url = (api_base_url or "https://api.tavily.com").rstrip("/")

    def _post() -> dict[str, Any]:
        response = requests.post(
            f"{base_url}/search",
            json=body,
            headers=headers,
            timeout=timeout_seconds,
        )
        if response.status_code != 200:
            raise ValueError(
                f"Error {response.status_code}: {_response_message(response)}"
            )
        result = json.loads(response.content.decode("utf-8-sig"))
        return result if isinstance(result, dict) else {}

    return await to_thread(_post)


def _unavailable(
    request: SearchRequest,
    start: float,
    error_type: str,
    error: str,
) -> SearchResult:
    duration_ms = int((time.perf_counter() - start) * 1000)
    return SearchResult(
        outcome="unavailable",
        provider="tavily",
        query=request.query,
        effective_query=request.query,
        error=error,
        attempts=[
            SearchAttempt(
                provider="tavily",
                outcome="unavailable",
                duration_ms=duration_ms,
                error_type=error_type,
                error=error,
            )
        ],
    )


def _response_message(response: requests.Response) -> str:
    try:
        payload = json.loads(response.content.decode("utf-8-sig"))
    except (UnicodeDecodeError, ValueError):
        return response.reason or "provider request failed"
    detail = payload.get("detail") if isinstance(payload, dict) else None
    if isinstance(detail, dict):
        return str(detail.get("error") or response.reason or "provider request failed")
    return str(detail or payload.get("error") or response.reason or "provider request failed")


def _error_type(message: str) -> str:
    lowered = message.lower()
    if "401" in lowered or "unauthorized" in lowered:
        return "unauthorized"
    if "403" in lowered or "forbidden" in lowered:
        return "forbidden"
    if "429" in lowered or "rate" in lowered:
        return "rate_limited"
    if "timeout" in lowered:
        return "timeout"
    return "provider_error"


def _redact(message: str, secret: str) -> str:
    return message.replace(secret, "[redacted]") if secret else message


def _bounded_int(value: Any, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, min(parsed, maximum))


def _provider_result_limit(request: SearchRequest) -> int:
    if request.include_url_prefixes:
        return min(10, request.max_results * 2)
    return request.max_results


def _effective_query(request: SearchRequest) -> str:
    prefixes = [
        f"site:{prefix.removeprefix('https://').removeprefix('http://')}"
        for prefix in request.include_url_prefixes
    ]
    return " ".join([*prefixes, request.query])[:500]
