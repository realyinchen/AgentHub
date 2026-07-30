from __future__ import annotations

from app.services.external_capabilities.contracts import (
    ExternalEvidenceSource,
    WeatherEvidence,
    WeatherGetInput,
)
from app.services.external_search.contracts import SearchResult


class WeatherReceiptSanitizer:
    """Project provider results into the only weather payload stored in Receipt."""

    def sanitize(
        self,
        request: WeatherGetInput,
        result: SearchResult,
    ) -> WeatherEvidence:
        sources = [
            ExternalEvidenceSource(
                title=_bounded(hit.title, 300),
                url=_bounded(hit.url, 2_000),
                snippet=_bounded(hit.snippet, 1_000),
                published_date=_bounded(hit.published_date, 64),
            )
            for hit in result.hits[:3]
            if str(hit.url or "").strip()
        ]
        if result.outcome == "found" and sources:
            status = "ok"
            error = ""
        elif result.outcome == "empty" or (
            result.outcome == "found" and not sources
        ):
            status = "empty_result"
            error = ""
        else:
            status = "unavailable"
            error = "weather_source_unavailable"
        return WeatherEvidence(
            status=status,
            location=request.location,
            date=request.date,
            units=request.units,
            sources=sources,
            error=error,
        )


def _bounded(value: str, limit: int) -> str:
    return " ".join(str(value or "").split())[:limit]


__all__ = ["WeatherReceiptSanitizer"]

