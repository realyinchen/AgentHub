from __future__ import annotations

import re
from collections.abc import Sequence

from app.services.routing.interaction_contracts import (
    BusinessRoutingContext,
    ExistingInformationDecision,
    GoalClause,
    GoalDecision,
    RoutingEvidence,
)


_FOLLOW_UP_RE = re.compile(
    r"^(?:再|继续|来几个|找几本类似|类似|刚才|上面|那个|这个|这些|"
    r"这本|那本|它|那|改成|more\b|continue\b|that\b|those\b)|"
    r"(?:把)?(?:这个|那个|它)(?:记住|保存)",
    re.I,
)
_FORBID_MEMORY_READ_RE = re.compile(
    r"不要(?:查|读取|使用)(?:我的)?(?:记忆|历史)|别查记忆|"
    r"do not (?:read|use|search) (?:my )?(?:memory|history)",
    re.I,
)


class ExistingInformationResolver:
    """Decide whether answering depends on conversation or durable memory."""

    def resolve(
        self,
        clause: GoalClause,
        goal: GoalDecision,
        evidence: Sequence[RoutingEvidence],
        context: BusinessRoutingContext,
    ) -> ExistingInformationDecision:
        intents = {item.intent for item in evidence if item.polarity != "opposes"}
        conversation = "not_required"
        memory = "not_required"
        rationale: list[str] = []
        confidence = 0.92

        if goal.kind == "recall_conversation":
            return ExistingInformationDecision(
                conversation_context=(
                    "required"
                    if context.conversation_turns
                    or context.recent_user_messages
                    else "unknown"
                ),
                long_term_memory="not_required",
                rationale=["current_thread_recall_uses_conversation_history"],
                confidence=(
                    0.99
                    if context.conversation_turns
                    or context.recent_user_messages
                    else 0.48
                ),
            )

        if _FORBID_MEMORY_READ_RE.search(clause.text):
            return ExistingInformationDecision(
                conversation_context=conversation,
                long_term_memory="forbidden",
                rationale=["explicit_long_term_memory_read_prohibition"],
                confidence=0.99,
            )

        if clause.ordinal == 0 and (
            clause.relation == "then" or _FOLLOW_UP_RE.search(clause.text)
        ):
            if context.active_subject or context.previous_primary_intent:
                conversation = "required"
                rationale.append("follow_up_has_business_context")
            else:
                conversation = "unknown"
                confidence = 0.48
                rationale.append("follow_up_missing_business_context")

        if goal.kind == "retrieve_personal_context":
            memory = "required"
            rationale.append("personal_context_answer_depends_on_memory")
        elif goal.kind == "recommend_books":
            if re.search(r"按(?:这个|我的|上述)?偏好", clause.text):
                memory = "required"
                rationale.append("recommendation_explicitly_depends_on_preferences")
            else:
                memory = "optional"
                rationale.append("personalization_is_optional")

        return ExistingInformationDecision(
            conversation_context=conversation,
            long_term_memory=memory,
            rationale=rationale or ["no_existing_information_dependency"],
            confidence=confidence,
        )
