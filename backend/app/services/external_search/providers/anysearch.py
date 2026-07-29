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


class AnySearchProvider:
    name = "anysearch"

    async def search(self, request: SearchRequest) -> SearchResult:
        start = time.perf_counter()
        config = await resolve_search_provider(
            self.name,
            env_setting="ANYSEARCH_API_KEY",
            default_api_base_url="https://api.anysearch.com",
            allow_anonymous=True,
        )
        if not config.enabled:
            return _unavailable(
                request,
                start,
                "not_configured",
                config.error or "AnySearch is disabled",
            )

        timeout_seconds = _bounded_int(
            config.settings.get("timeout_seconds"),
            20,
            3,
            60,
        )
        effective_query = _effective_query(request)
        try:
            payload = await run_anysearch_request(
                api_key=config.api_key,
                api_base_url=config.api_base_url,
                query=effective_query,
                max_results=_provider_result_limit(request),
                language=request.language or "zh",
                zone=request.zone or ("cn" if _contains_cjk(request.query) else "intl"),
                category=request.category,
                timeout_seconds=timeout_seconds,
            )
        except Exception as exc:
            message = _redact(str(exc) or exc.__class__.__name__, config.api_key)
            return _unavailable(
                request,
                start,
                _error_type(message),
                message,
                effective_query=effective_query,
            )

        data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
        hits = [
            SearchHit(
                title=str(item.get("title") or ""),
                url=str(item.get("url") or ""),
                snippet=str(item.get("snippet") or ""),
                content=str(item.get("content") or item.get("snippet") or ""),
                published_date=str(
                    item.get("published_date")
                    or item.get("published_at")
                    or item.get("date")
                    or ""
                ),
                provider=self.name,
                metadata={},
            )
            for item in data.get("results") or []
            if isinstance(item, dict) and item.get("url")
        ]
        duration_ms = int((time.perf_counter() - start) * 1000)
        outcome = "found" if hits else "empty"
        return SearchResult(
            outcome=outcome,
            provider=self.name,
            query=request.query,
            effective_query=effective_query,
            hits=hits,
            attempts=[
                SearchAttempt(
                    provider=self.name,
                    outcome=outcome,
                    duration_ms=duration_ms,
                    upstream_request_id=str(payload.get("request_id") or ""),
                )
            ],
            metadata=dict(data.get("metadata") or {}),
        )


async def run_anysearch_request(
    *,
    api_key: str,
    query: str,
    max_results: int,
    language: str,
    zone: str,
    category: str,
    timeout_seconds: int,
    api_base_url: str = "",
) -> dict[str, Any]:
    """AnySearch REST transport. Anonymous use omits Authorization entirely."""

    headers = {
        "Content-Type": "application/json",
        "X-Client-Source": "test01-book-assistant",
    }
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    payload = {
        "query": query,
        "max_results": max_results,
        "tag": "news.general" if category == "news" else "general.general",
        "zone": zone,
        "language": language,
        "format": "json",
    }
    base_url = (api_base_url or "https://api.anysearch.com").rstrip("/")

    def _post() -> dict[str, Any]:
        response = requests.post(
            f"{base_url}/v1/search",
            json=payload,
            headers=headers,
            timeout=timeout_seconds,
        )
        try:
            result = json.loads(response.content.decode("utf-8-sig"))
        except (UnicodeDecodeError, ValueError):
            result = {}
        code = result.get("code") if isinstance(result, dict) else None
        if response.status_code != 200 or code not in {None, 0}:
            message = (
                str(result.get("message") or "").strip()
                if isinstance(result, dict)
                else ""
            )
            raise ValueError(
                f"Error {response.status_code}: "
                f"{message or response.reason or 'provider request failed'}"
            )
        return result if isinstance(result, dict) else {}

    return await to_thread(_post)


def _effective_query(request: SearchRequest) -> str:
    terms = [request.query]
    terms.extend(
        f"site:{prefix.removeprefix('https://').removeprefix('http://')}"
        for prefix in request.include_url_prefixes
    )
    terms.extend(f"site:{domain}" for domain in request.include_domains)
    terms.extend(f"-site:{domain}" for domain in request.exclude_domains)
    return " ".join(terms)[:500]


def _contains_cjk(value: str) -> bool:
    return any("\u3400" <= character <= "\u9fff" for character in value)


def _unavailable(
    request: SearchRequest,
    start: float,
    error_type: str,
    error: str,
    *,
    effective_query: str = "",
) -> SearchResult:
    duration_ms = int((time.perf_counter() - start) * 1000)
    return SearchResult(
        outcome="unavailable",
        provider="anysearch",
        query=request.query,
        effective_query=effective_query or request.query,
        error=error,
        attempts=[
            SearchAttempt(
                provider="anysearch",
                outcome="unavailable",
                duration_ms=duration_ms,
                error_type=error_type,
                error=error,
            )
        ],
    )


def _error_type(message: str) -> str:
    lowered = message.lower()
    if "401" in lowered or "unauthorized" in lowered:
        return "unauthorized"
    if "402" in lowered:
        return "payment_required"
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
