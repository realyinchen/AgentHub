from __future__ import annotations

import re

from app.services.external_search.contracts import SearchRequest


_CJK_RE = re.compile(r"[\u3400-\u9fff]")
_PROVIDERS = ("tavily", "anysearch")


def provider_order(
    request: SearchRequest,
    *,
    previously_used: tuple[str, ...] = (),
) -> tuple[str, ...]:
    """Return a deterministic provider order; it performs no I/O."""

    if request.zone == "cn" or _CJK_RE.search(request.query):
        ordered = ["anysearch", "tavily"]
    elif request.include_domains or request.time_range or request.category == "news":
        ordered = list(_PROVIDERS)
    else:
        ordered = list(_PROVIDERS)

    used = {item.strip().lower() for item in previously_used}
    return tuple(
        [item for item in ordered if item not in used]
        + [item for item in ordered if item in used]
    )
