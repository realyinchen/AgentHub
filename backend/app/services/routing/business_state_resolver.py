from __future__ import annotations

import re
from collections.abc import Sequence

from app.services.routing.interaction_contracts import (
    BusinessStateDecision,
    GoalClause,
    GoalDecision,
    RoutingEvidence,
)


_FORBID_RE = re.compile(
    r"不要(?:修改|更新|删除|添加|标记)|别(?:改|删|添加)|"
    r"do not (?:change|update|delete|add)",
    re.I,
)
_STATE_CHANGE_RE = re.compile(
    r"标记为|更新为|修改为|改成|删除|移除|添加到|加入|设为|"
    r"mark as|update|change to|delete|remove|add to|set to",
    re.I,
)


class BusinessStateResolver:
    """Identify requested business mutations without naming an operation."""

    def resolve(
        self,
        clause: GoalClause,
        goal: GoalDecision,
        evidence: Sequence[RoutingEvidence],
    ) -> BusinessStateDecision:
        text = clause.text
        if _FORBID_RE.search(text):
            return BusinessStateDecision(
                disposition="forbidden",
                rationale=["explicit_business_state_change_prohibition"],
                confidence=0.98,
            )
        if _STATE_CHANGE_RE.search(text) and goal.kind == "record_reading_feedback":
            return BusinessStateDecision(
                disposition="explicitly_requested",
                target=goal.domain,
                rationale=["explicit_business_state_change_request"],
                confidence=0.94,
            )
        if goal.kind == "record_reading_feedback":
            return BusinessStateDecision(
                disposition="proposed",
                target="books",
                rationale=["resolved_reading_feedback_changes_book_state"],
                confidence=0.91,
            )
        if any(
            item.intent == "reading_feedback" and item.polarity != "opposes"
            for item in evidence
        ):
            return BusinessStateDecision(
                disposition="proposed",
                target="books",
                rationale=["reading_feedback_may_change_business_state"],
                confidence=0.72,
            )
        return BusinessStateDecision(
            disposition="none",
            rationale=["no_business_state_change"],
            confidence=0.93,
        )
