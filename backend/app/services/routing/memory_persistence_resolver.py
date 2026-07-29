from __future__ import annotations

import re
from collections.abc import Sequence

from app.services.routing.interaction_contracts import (
    BusinessRoutingContext,
    GoalClause,
    GoalDecision,
    MemoryPersistenceDecision,
    RoutingEvidence,
)
from app.services.routing.speech_act import analyze_speech_act
from app.services.routing.clarification import is_memory_clarification_answer


_FORBID_RE = re.compile(
    r"不要记住|别记|不要保存|请勿保存|忘掉|forget|do not remember|don't remember",
    re.I,
)
_EXPLICIT_RE = re.compile(
    r"记住|记一下|保存(?:这个|下来)?|以后要记得|remember|save this|keep in mind",
    re.I,
)
_DURABLE_FACT_RE = re.compile(
    r"我(?:叫|是|喜欢|不喜欢|偏好|通常|长期|住在|的生日|的职业)|"
    r"my (?:name|preference|birthday|job)|i (?:like|prefer|live|work)",
    re.I,
)
_CORRECTION_RE = re.compile(
    r"不叫|改成|改为|改叫|以后叫我|纠正|其实是|不是.+而是|"
    r"\b(?:correct|correction|instead|call me)\b",
    re.I,
)
_REFERENTIAL_TARGET_RE = re.compile(
    r"^(?:我的(?:名字|姓名|称呼|信息|资料|偏好|喜好|习惯|状态)|"
    r"这个|那个|这些|那些|它|他|她|这件事|那件事|"
    r"my name|this|that|it|him|her)$",
    re.I,
)


class MemoryPersistenceResolver:
    """Propose persistence; it never writes memory or authorizes a write."""

    def resolve(
        self,
        clause: GoalClause,
        goal: GoalDecision,
        evidence: Sequence[RoutingEvidence],
        context: BusinessRoutingContext,
    ) -> MemoryPersistenceDecision:
        text = clause.text
        speech = analyze_speech_act(text)
        if speech.metalinguistic:
            return MemoryPersistenceDecision(
                disposition="not_warranted",
                rationale=["quoted_memory_language_is_not_a_persistence_request"],
                confidence=0.99,
            )
        if _FORBID_RE.search(text):
            return MemoryPersistenceDecision(
                disposition="forbidden",
                rationale=["explicit_memory_persistence_prohibition"],
                confidence=0.99,
            )
        if is_memory_clarification_answer(
            text,
            context.pending_memory_write,
        ):
            pending = context.pending_memory_write
            assert pending is not None
            return MemoryPersistenceDecision(
                disposition="explicitly_requested",
                subject=pending.target_expression,
                operation="create",
                target_expression=pending.target_expression,
                explicit=True,
                conversation_context_required=False,
                pending_clarification=pending,
                rationale=["continuation_of_memory_clarification"],
                confidence=0.99,
            )
        if _EXPLICIT_RE.search(text) and goal.kind == "share_personal_information":
            subject = _subject_after_colon(text)
            return MemoryPersistenceDecision(
                disposition="explicitly_requested",
                subject=subject,
                operation="correct" if _CORRECTION_RE.search(text) else "create",
                target_expression=subject,
                explicit=True,
                conversation_context_required=bool(
                    subject and _REFERENTIAL_TARGET_RE.fullmatch(subject)
                ),
                rationale=["explicit_memory_persistence_request"],
                confidence=0.97,
            )
        if (
            goal.kind == "share_personal_information"
            and _DURABLE_FACT_RE.search(text)
        ):
            return MemoryPersistenceDecision(
                disposition="candidate",
                subject=text,
                operation="correct" if _CORRECTION_RE.search(text) else "create",
                target_expression=text,
                explicit=False,
                rationale=["durable_personal_fact_candidate"],
                confidence=0.78,
            )
        if goal.kind == "share_personal_information" and any(
            item.intent == "memory_update" and item.polarity != "opposes"
            for item in evidence
        ):
            return MemoryPersistenceDecision(
                disposition="candidate",
                subject=text if goal.domain == "personal_context" else None,
                operation="create",
                target_expression=(
                    text if goal.domain == "personal_context" else None
                ),
                explicit=False,
                rationale=["legacy_memory_evidence_requires_admission"],
                confidence=0.65,
            )
        return MemoryPersistenceDecision(
            disposition="not_warranted",
            rationale=["no_durable_personal_information"],
            confidence=0.93,
        )


def _subject_after_colon(text: str) -> str | None:
    parts = re.split(r"[:：]", text, maxsplit=1)
    subject = parts[1].strip() if len(parts) == 2 else text.strip()
    subject = re.sub(
        r"^(?:先)?(?:请你|请|帮我)?(?:记住|记一下|记下来|保存)\s*",
        "",
        subject,
        flags=re.I,
    ).strip()
    return subject or None
