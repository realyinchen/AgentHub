from __future__ import annotations

from app.services.external_capabilities.contracts import (
    BookEvidence,
    BookSearchInput,
    ExternalEvidenceSource,
)
from app.services.external_search.contracts import SearchResult


class BookSearchReceiptSanitizer:
    """Project public search hits into read-only book candidate evidence."""

    def sanitize(
        self,
        request: BookSearchInput,
        result: SearchResult,
    ) -> BookEvidence:
        sources = [
            ExternalEvidenceSource(
                title=_bounded(hit.title, 300),
                url=_bounded(hit.url, 2_000),
                snippet=_bounded(hit.snippet, 1_000),
                published_date=_bounded(hit.published_date, 64),
            )
            for hit in result.hits[: request.limit]
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
            error = "book_source_unavailable"
        return BookEvidence(
            status=status,
            query=request.query,
            sources=sources,
            error=error,
        )


def _bounded(value: str, limit: int) -> str:
    return " ".join(str(value or "").split())[:limit]


__all__ = ["BookSearchReceiptSanitizer"]

