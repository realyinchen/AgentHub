from __future__ import annotations

from app.services.routing.interaction_contracts import (
    BusinessStateDecision,
    ExistingInformationDecision,
    ExternalInformationDecision,
    GoalClause,
    GoalDecision,
    MemoryPersistenceDecision,
    PlanningDecision,
)


class PlanningRequirementResolver:
    """Select planning depth from resolved needs, never from tool count."""

    def resolve(
        self,
        *,
        clause: GoalClause,
        goal: GoalDecision,
        existing: ExistingInformationDecision,
        external: ExternalInformationDecision,
        memory: MemoryPersistenceDecision,
        state: BusinessStateDecision,
        clause_count: int,
    ) -> PlanningDecision:
        if (
            existing.conversation_context == "unknown"
            or goal.confidence < 0.50
            or memory.disposition == "uncertain"
            or state.disposition == "uncertain"
        ):
            return PlanningDecision(
                mode="clarification_required",
                rationale=["unresolved_decision_axis"],
                confidence=0.90,
            )
        if goal.kind == "research_topic" or clause_count >= 3:
            return PlanningDecision(
                mode="decomposition_required",
                rationale=["multi_step_goal"],
                confidence=0.94,
            )
        if (
            existing.conversation_context == "required"
            or
            existing.long_term_memory == "required"
            or external.external_information == "required"
            or memory.disposition in {"candidate", "explicitly_requested"}
            or state.disposition in {"proposed", "explicitly_requested"}
            or goal.kind
            in {
                "recommend_books",
                "find_books",
                "review_recommendation_history",
                "record_reading_feedback",
            }
        ):
            return PlanningDecision(
                mode="static_workflow",
                rationale=["resolved_non_direct_requirement"],
                confidence=0.91,
            )
        return PlanningDecision(
            mode="direct_answer",
            rationale=["all_required_information_is_already_available"],
            confidence=0.92,
        )
