from __future__ import annotations

import re
from datetime import datetime
from collections.abc import Iterable
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.services.research.query import normalize_research_query


SearchTimeRange = Literal["day", "week", "month", "year"]

_BOOK_RE = re.compile(r"图书|书籍|书单|新书|童书|\bbooks?\b", re.IGNORECASE)
_BOOK_MARKETPLACE_DOMAINS = [
    "taobao.com",
    "tmall.com",
    "jd.com",
    "pinduoduo.com",
    "dangdang.com",
    "amazon.cn",
]


class ResearchSearchRequest(BaseModel):
    """Business-only input for one evidence-oriented web search."""

    objective: str = Field(min_length=1)
    query: str = Field(min_length=1, max_length=300)
    max_results: int = Field(default=5, ge=1, le=10)
    detail: Literal["standard", "deep"] = "deep"
    time_range: SearchTimeRange | None = None
    include_domains: list[str] = Field(default_factory=list, max_length=300)
    exclude_domains: list[str] = Field(default_factory=list, max_length=150)
    include_url_prefixes: list[str] = Field(default_factory=list, max_length=20)
    language: str = ""
    category: Literal["general", "news"] = "general"
    requirements: list[str] = Field(default_factory=list)

    def tool_arguments(self) -> dict[str, object]:
        return {
            "query": self.query,
            "max_results": self.max_results,
            "detail": self.detail,
            "time_range": self.time_range,
            "include_domains": list(self.include_domains),
            "exclude_domains": list(self.exclude_domains),
            "include_url_prefixes": list(self.include_url_prefixes),
            "language": self.language,
            "category": self.category,
        }


def build_research_search_request(
    objective: str,
    *,
    constraints: Iterable[Any] = (),
) -> ResearchSearchRequest:
    """Compile canonical routing constraints into search-domain filters."""

    normalized = normalize_research_query(objective)
    query_terms = [normalized]
    requirements: list[str] = []
    include_domains: list[str] = []
    exclude_domains: list[str] = []
    time_range: SearchTimeRange | None = None
    language = ""
    include_url_prefixes: list[str] = []
    max_results = 5

    if _BOOK_RE.search(normalized):
        requirements.append("book")
        query_terms.append("图书 出版 作者")
        exclude_domains.extend(_BOOK_MARKETPLACE_DOMAINS)
    for constraint in constraints:
        field = str(_constraint_value(constraint, "field") or "").strip()
        value = _constraint_value(constraint, "value")
        if field == "published_at":
            time_range = "year"
            requirements.append("recency")
            query_terms.extend([str(datetime.now().year), "出版 发布"])
        elif field == "rating":
            requirements.append("review")
            query_terms.append("书评 评分 推荐 榜单")
        elif field == "source_domain":
            values = value if isinstance(value, list) else [value]
            include_domains.extend(str(item or "") for item in values)
        elif field == "language":
            language = "zh" if "中" in str(value or "") else str(value or "")
        elif field == "result_limit":
            try:
                max_results = max(1, min(int(value), 10))
            except (TypeError, ValueError):
                max_results = 5
            requirements.append("result_limit")
    if (
        "book" in requirements
        and any(domain.endswith("douban.com") for domain in include_domains)
    ):
        query_terms = [
            "site:book.douban.com/subject/",
            normalized,
            "豆瓣 评分 作者 出版社 高分 书评",
        ]
        include_url_prefixes = ["https://book.douban.com/subject/"]

    return ResearchSearchRequest(
        objective=normalized,
        query=_unique_query(" ".join(query_terms)),
        max_results=max_results,
        time_range=time_range,
        include_domains=list(dict.fromkeys(filter(None, include_domains))),
        exclude_domains=list(dict.fromkeys(exclude_domains)),
        include_url_prefixes=include_url_prefixes,
        language=language,
        requirements=list(dict.fromkeys(requirements)),
    )


def _unique_query(query: str) -> str:
    terms = query.split()
    return " ".join(dict.fromkeys(terms))[:300].strip()


def _constraint_value(constraint: Any, field: str) -> Any:
    if isinstance(constraint, dict):
        return constraint.get(field)
    return getattr(constraint, field, None)
