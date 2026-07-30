from __future__ import annotations

from app.services.external_capabilities.contracts import (
    ExternalEvidenceSource,
    WebEvidence,
    WebSearchInput,
)
from app.services.external_search.contracts import SearchResult


class WebSearchReceiptSanitizer:
    """Project gateway output into bounded citation evidence."""

    def sanitize(
        self,
        request: WebSearchInput,
        result: SearchResult,
    ) -> WebEvidence:
        sources = [
            ExternalEvidenceSource(
                title=_bounded(hit.title, 300),
                url=_bounded(hit.url, 2_000),
                snippet=_bounded(hit.snippet, 1_000),
                published_date=_bounded(hit.published_date, 64),
            )
            for hit in result.hits[: request.max_results]
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
            error = "web_source_unavailable"
        return WebEvidence(
            status=status,
            query=request.query,
            sources=sources,
            error=error,
        )


def _bounded(value: str, limit: int) -> str:
    return " ".join(str(value or "").split())[:limit]


__all__ = ["WebSearchReceiptSanitizer"]

