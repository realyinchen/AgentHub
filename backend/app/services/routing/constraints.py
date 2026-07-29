from __future__ import annotations

import re

from app.services.routing.contracts import ConstraintOperator, RoutingConstraint


_FILTER_PATTERNS: tuple[
    tuple[str, ConstraintOperator, re.Pattern[str]],
    ...,
] = (
    (
        "source_domain",
        "in",
        re.compile(r"豆瓣|douban", re.IGNORECASE),
    ),
    (
        "published_at",
        "gte",
        re.compile(r"最新|最近|近(?:一|两|三|\d+)年|latest|recent", re.IGNORECASE),
    ),
    (
        "rating",
        "gte",
        re.compile(r"好评|高分|口碑好|well[- ]reviewed|highly rated", re.IGNORECASE),
    ),
    (
        "language",
        "equals",
        re.compile(r"中文版|中译本|中文|chinese edition", re.IGNORECASE),
    ),
    (
        "excluded_traits",
        "not_contains",
        re.compile(r"不要|避免|别太|不喜欢|avoid|without", re.IGNORECASE),
    ),
)

_RESULT_LIMIT_RE = re.compile(
    r"(?:给我|推荐|列出|选择|要)?\s*(\d{1,2})\s*本",
    re.IGNORECASE,
)


def extract_routing_constraints(text: str) -> list[RoutingConstraint]:
    constraints: list[RoutingConstraint] = []
    for field, operator, pattern in _FILTER_PATTERNS:
        match = pattern.search(text)
        if match is None:
            continue
        constraints.append(
            RoutingConstraint(
                field=field,
                operator=operator,
                value=(
                    ["book.douban.com"]
                    if field == "source_domain"
                    else match.group(0)
                ),
                source="rule",
                reason="explicit_user_filter",
            )
        )
    limit_match = _RESULT_LIMIT_RE.search(text)
    if limit_match is not None:
        constraints.append(
            RoutingConstraint(
                field="result_limit",
                operator="equals",
                value=max(1, min(int(limit_match.group(1)), 10)),
                source="rule",
                reason="explicit_user_filter",
            )
        )
    return constraints
