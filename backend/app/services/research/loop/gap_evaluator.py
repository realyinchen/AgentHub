from __future__ import annotations

from typing import Any

from app.services.research.evidence_quality import (
    assess_evidence_candidate,
    source_host,
)
from app.services.research.loop.contracts import (
    ResearchGapAssessment,
    ResearchLoopBudget,
    ResearchRoundSources,
)
from app.services.research.source_acquisition import ResearchSourceRecord


_REQUIREMENT_GAPS = (
    "missing_recency_evidence",
    "missing_review_evidence",
    "missing_book_evidence",
)

_GAP_DESCRIPTIONS = {
    "missing_recency_evidence": "未找到带有明确发布日期、可用于判断“最新”的证据。",
    "missing_review_evidence": "未找到可核验评分或评论依据，无法判断“好评”。",
    "missing_book_evidence": "未找到可核验的具体图书信息。",
    "insufficient_independent_sources": "独立来源不足，尚不能完成交叉验证。",
    "no_publishable_evidence": "没有找到可进入研究报告的可核验证据。",
}


def evaluate_research_gaps(
    *,
    round_index: int,
    rounds: list[ResearchRoundSources | dict[str, Any]],
    budget: ResearchLoopBudget | dict[str, Any],
) -> ResearchGapAssessment:
    """Decide whether another search round is needed from visible evidence."""

    loop_budget = ResearchLoopBudget.model_validate(budget)
    sources = [
        ResearchRoundSources.model_validate(item)
        for item in rounds
    ]
    executed = [item for item in sources if item.executed]
    records = _unique_records(
        record
        for item in executed
        for record in item.source_records
    )
    reason_codes = list(
        dict.fromkeys(
            reason
            for item in executed
            for reason in item.rejection_reason_codes
        )
    )

    return evaluate_research_evidence_gaps(
        round_index=round_index,
        records=records,
        rejection_reason_codes=reason_codes,
        exhausted_queries=[
            item.task.query
            for item in executed
            if item.task.query
        ],
        budget=loop_budget,
        search_round_count=len(executed),
        objective=next(
            (
                item.task.objective
                for item in executed
                if item.task.objective
            ),
            "",
        ),
    )


def evaluate_research_evidence_gaps(
    *,
    round_index: int,
    records: list[ResearchSourceRecord | dict[str, Any]],
    rejection_reason_codes: list[str],
    exhausted_queries: list[str],
    budget: ResearchLoopBudget | dict[str, Any],
    search_round_count: int = 1,
    objective: str = "",
) -> ResearchGapAssessment:
    """Shared evidence-gap policy for canonical and compatibility runtimes."""

    loop_budget = ResearchLoopBudget.model_validate(budget)
    normalized_records = _unique_records(
        ResearchSourceRecord.model_validate(item)
        for item in records
    )
    assessments = [
        (
            record,
            assess_evidence_candidate(
                claim=record.claim,
                query=objective,
                source_title=record.source_title,
                source_url=record.source_url,
                published_date=_record_published_date(record),
            ),
        )
        for record in normalized_records
    ]
    publishable_records = [
        record
        for record, assessment in assessments
        if assessment.publishable
    ]
    independent_sources = {
        source_host(record.source_url)
        or record.source_title.strip().lower()
        for record in publishable_records
        if source_host(record.source_url) or record.source_title.strip()
    }
    reason_codes = list(
        dict.fromkeys(
            [
                *rejection_reason_codes,
                *[
                    reason
                    for _record, assessment in assessments
                    for reason in assessment.reason_codes
                ],
            ]
        )
    )

    gaps: list[str] = []
    if not publishable_records:
        gaps.extend(
            reason
            for reason in _REQUIREMENT_GAPS
            if reason in reason_codes
        )
        if not gaps:
            gaps.append("no_publishable_evidence")
    elif len(independent_sources) < loop_budget.min_independent_sources:
        gaps.append("insufficient_independent_sources")

    satisfied = not gaps
    can_continue = bool(gaps) and round_index < loop_budget.max_search_rounds
    if satisfied:
        stop_reason = "evidence_satisfied"
    elif can_continue:
        stop_reason = "continue"
    else:
        stop_reason = "search_budget_exhausted"

    return ResearchGapAssessment(
        round_index=round_index,
        gaps=gaps,
        gap_descriptions=[
            _GAP_DESCRIPTIONS.get(gap, gap)
            for gap in gaps
        ],
        satisfied=satisfied,
        should_continue=can_continue,
        stop_reason=stop_reason,
        accepted_record_count=len(publishable_records),
        independent_source_count=len(independent_sources),
        exhausted_queries=list(dict.fromkeys(exhausted_queries)),
        next_actions=(
            ["plan_next_search"]
            if can_continue
            else ["build_research_report"]
        ),
        metadata={
            "search_round_count": search_round_count,
            "rejection_reason_codes": reason_codes,
            "candidate_record_count": len(normalized_records),
            "publishable_record_count": len(publishable_records),
            "max_search_rounds": loop_budget.max_search_rounds,
        },
    )


def _unique_records(records):
    unique = []
    seen: set[tuple[str, str]] = set()
    for record in records:
        key = (
            record.source_url.strip().lower(),
            record.claim.strip().lower(),
        )
        if key in seen:
            continue
        seen.add(key)
        unique.append(record)
    return unique


def _record_published_date(record: ResearchSourceRecord) -> str:
    metadata = record.metadata if isinstance(record.metadata, dict) else {}
    return str(
        metadata.get("published_date")
        or metadata.get("published_at")
        or ""
    ).strip()
