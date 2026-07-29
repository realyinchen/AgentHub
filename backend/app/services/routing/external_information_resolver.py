from __future__ import annotations

import re
from collections.abc import Sequence

from app.services.routing.interaction_contracts import (
    ExternalInformationDecision,
    GoalClause,
    GoalDecision,
    RoutingEvidence,
)
from app.services.routing.speech_act import analyze_speech_act


_FORBID_EXTERNAL_RE = re.compile(
    r"不要(?:搜索|联网|查网)|别(?:搜索|联网|查天气)|无需(?:搜索|联网)|"
    r"不需要.*(?:查|搜索).*(?:实时)?天气|"
    r"禁止(?:搜索|联网)|do not search|don't search|without (?:search|browsing)",
    re.I,
)
_CURRENT_RE = re.compile(
    r"今天|现在|当前|最新|实时|现任|价格|汇率|新闻|"
    r"today|current|latest|now|real[- ]?time|price|news",
    re.I,
)
_EXPLICIT_EXTERNAL_RE = re.compile(
    r"搜索|联网|网上查|查一下|官网|search|browse|look up|find online",
    re.I,
)


class ExternalInformationResolver:
    """Resolve current/external information needs independently from goal."""

    def resolve(
        self,
        clause: GoalClause,
        goal: GoalDecision,
        evidence: Sequence[RoutingEvidence],
    ) -> ExternalInformationDecision:
        text = clause.text
        speech = analyze_speech_act(text)
        if speech.metalinguistic:
            return ExternalInformationDecision(
                current_information="not_required",
                external_information="not_required",
                rationale=["quoted_capability_language_is_not_an_external_request"],
                confidence=0.99,
            )
        if goal.kind in {"clarify_objective", "clarify_referent", "unknown"}:
            return ExternalInformationDecision(
                current_information="not_required",
                external_information="not_required",
                rationale=["unresolved_or_unknown_goal_cannot_require_external_data"],
                confidence=0.99,
            )
        if _FORBID_EXTERNAL_RE.search(text):
            return ExternalInformationDecision(
                current_information="forbidden",
                external_information="forbidden",
                rationale=["explicit_external_information_prohibition"],
                confidence=0.99,
            )
        if goal.kind in {
            "share_personal_information",
            "retrieve_personal_context",
            "record_reading_feedback",
            "review_recommendation_history",
        }:
            return ExternalInformationDecision(
                current_information="not_required",
                external_information="not_required",
                rationale=["goal_is_resolved_from_user_or_app_owned_state"],
                confidence=0.97,
            )

        current = "not_required"
        external = "not_required"
        rationale: list[str] = []
        confidence = 0.90

        if goal.domain == "weather":
            current = "required"
            external = "required"
            rationale.append("weather_answer_requires_current_external_information")
        elif goal.kind == "research_topic":
            external = "required"
            current = "optional" if not _CURRENT_RE.search(text) else "required"
            rationale.append("research_requires_external_evidence")
        elif goal.kind == "answer_current_question":
            external = "required"
            current = "required"
            rationale.append("current_answer_requires_external_grounding")
        elif goal.kind == "answer_factual_question":
            if goal.domain == "books" and re.search(
                r"谁写|作者|who wrote",
                text,
                re.I,
            ):
                external = "not_required"
                current = "not_required"
                rationale.append("stable_authorship_fact_can_use_model_knowledge")
            else:
                external = "required"
                current = "required" if _CURRENT_RE.search(text) else "optional"
                rationale.append("factual_entity_answer_requires_external_grounding")
        elif _CURRENT_RE.search(text):
            current = "required"
            external = "required"
            rationale.append("explicit_temporal_freshness")
        elif _EXPLICIT_EXTERNAL_RE.search(text):
            external = "required"
            rationale.append("explicit_external_information_request")
        elif goal.kind == "recommend_books":
            external = "optional"
            rationale.append("external_catalog_may_improve_recommendation")

        return ExternalInformationDecision(
            current_information=current,
            external_information=external,
            rationale=rationale or ["stable_answer_does_not_require_external_information"],
            confidence=confidence,
        )
