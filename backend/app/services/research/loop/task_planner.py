from __future__ import annotations

from typing import Any

from app.services.research.loop.contracts import (
    ResearchGapAssessment,
    ResearchLoopBudget,
    ResearchSearchTask,
)
from app.services.research.search_policy import build_research_search_request


_GAP_QUERY_TERMS = {
    "missing_recency_evidence": "出版日期 新书 发布 今年",
    "missing_review_evidence": "评分 书评 读者评论 高分榜单",
    "missing_book_evidence": "图书 作者 出版社 书目",
    "insufficient_independent_sources": "独立书评 出版社 编辑推荐",
    "no_publishable_evidence": "权威来源 详细介绍",
}


def plan_research_search_task(
    *,
    objective: str,
    round_index: int,
    budget: ResearchLoopBudget | dict[str, Any],
    constraints: list[dict[str, Any]] | None = None,
    previous_assessment: ResearchGapAssessment | dict[str, Any] | None = None,
) -> ResearchSearchTask:
    """Create one provider-neutral search task from the current evidence gap."""

    loop_budget = ResearchLoopBudget.model_validate(budget)
    base = build_research_search_request(
        objective,
        constraints=constraints or [],
    )
    previous = (
        ResearchGapAssessment.model_validate(previous_assessment)
        if previous_assessment is not None
        else None
    )

    if round_index > loop_budget.max_search_rounds:
        raise ValueError("research round exceeds the configured search budget")

    if previous is not None and not previous.should_continue:
        return ResearchSearchTask(
            round_index=round_index,
            objective=base.objective,
            purpose="no_op",
            query=base.query,
            should_search=False,
            target_gaps=list(previous.gaps),
            exhausted_queries=list(previous.exhausted_queries),
            max_results=loop_budget.max_results_per_round,
            detail=base.detail,
            time_range=base.time_range,
            include_domains=base.include_domains,
            exclude_domains=base.exclude_domains,
            include_url_prefixes=base.include_url_prefixes,
            language=base.language,
            category=base.category,
            metadata={"stop_reason": previous.stop_reason},
        )

    target_gaps = list(previous.gaps) if previous is not None else []
    suffix = " ".join(
        _GAP_QUERY_TERMS[gap]
        for gap in target_gaps
        if gap in _GAP_QUERY_TERMS
    )
    query = _unique_query(f"{base.query} {suffix}")
    return ResearchSearchTask(
        round_index=round_index,
        objective=base.objective,
        purpose=(
            "initial_evidence"
            if round_index == 1
            else "gap_repair"
        ),
        query=query,
        should_search=True,
        target_gaps=target_gaps,
        exhausted_queries=(
            list(previous.exhausted_queries)
            if previous is not None
            else []
        ),
        max_results=loop_budget.max_results_per_round,
        detail=base.detail,
        time_range=base.time_range,
        include_domains=base.include_domains,
        exclude_domains=base.exclude_domains,
        include_url_prefixes=base.include_url_prefixes,
        language=base.language,
        category=base.category,
        metadata={
            "requirements": base.requirements,
            "query_changed": bool(previous is not None and query != base.query),
        },
    )


def _unique_query(value: str) -> str:
    return " ".join(dict.fromkeys(str(value or "").split()))[:300].strip()
