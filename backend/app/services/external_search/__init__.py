"""Provider-neutral external search boundary."""

from app.services.external_search.contracts import (
    SearchAttempt,
    SearchHit,
    SearchRequest,
    SearchResult,
)
from app.services.external_search.gateway import SearchGateway, get_search_gateway

__all__ = [
    "SearchAttempt",
    "SearchGateway",
    "SearchHit",
    "SearchRequest",
    "SearchResult",
    "get_search_gateway",
]
