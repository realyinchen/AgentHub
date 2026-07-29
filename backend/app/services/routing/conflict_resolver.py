from __future__ import annotations

from collections.abc import Sequence

from app.services.routing.interaction_contracts import (
    AbstractCapability,
    AxisConfidence,
    ClauseDecision,
    DecisionConstraint,
    InteractionDecision,
    PlanningDecision,
)


class DecisionConflictResolver:
    """Apply prohibitions and combine clause decisions into one interaction."""

    def resolve(
        self,
        *,
        clauses: Sequence[ClauseDecision],
        constraints: Sequence[DecisionConstraint],
        evidence_limitations: Sequence[str] = (),
    ) -> InteractionDecision:
        if not clauses:
            raise ValueError("at least one clause decision is required")

        global_prohibitions = _global_prohibitions(clauses)
        conflict_questions = _conflict_questions(
            clauses,
            global_prohibitions,
        )
        normalized_clauses = [
            _apply_global_prohibitions(clause, global_prohibitions)
            for clause in clauses
        ]
        unresolved = _unresolved_questions(normalized_clauses)
        unresolved.extend(
            question for question in conflict_questions if question not in unresolved
        )

        planning = _aggregate_planning(
            normalized_clauses,
            bool(unresolved),
            global_prohibitions,
        )
        goal_kinds = {item.goal.kind for item in normalized_clauses}
        if unresolved:
            status = "clarification_required"
        elif "clarify_objective" in goal_kinds:
            status = "clarification_required"
            unresolved.append("需要明确希望处理或查询的具体对象。")
            planning = PlanningDecision(
                mode="clarification_required",
                rationale=["request_object_is_missing"],
                confidence=0.99,
            )
        elif "unknown" in goal_kinds:
            status = "safe_default"
        elif evidence_limitations and _limitations_affect_decision(
            normalized_clauses
        ):
            status = "safe_default"
        else:
            status = "accepted"

        direct_answer_allowed = (
            status != "clarification_required"
            and planning.mode == "direct_answer"
            and any(
            _is_substantive_direct_clause(clause) for clause in normalized_clauses
            )
            and not any(
            clause.external_information.external_information == "required"
            or clause.external_information.current_information == "required"
            or clause.existing_information.conversation_context == "required"
            or clause.existing_information.long_term_memory == "required"
            or clause.memory_persistence.disposition
            in {"candidate", "explicitly_requested"}
            or clause.business_state.disposition
            in {"proposed", "explicitly_requested"}
            for clause in normalized_clauses
            )
        )

        return InteractionDecision(
            status=status,
            clauses=normalized_clauses,
            planning=planning,
            constraints=_dedupe_constraints(constraints),
            prohibited_capabilities=sorted(global_prohibitions),
            direct_answer_allowed=direct_answer_allowed,
            confidence_by_axis=AxisConfidence(
                goal=min(item.goal.confidence for item in normalized_clauses),
                existing_information=min(
                    item.existing_information.confidence
                    for item in normalized_clauses
                ),
                external_information=min(
                    item.external_information.confidence
                    for item in normalized_clauses
                ),
                memory_persistence=min(
                    item.memory_persistence.confidence
                    for item in normalized_clauses
                ),
                business_state=min(
                    item.business_state.confidence for item in normalized_clauses
                ),
                planning=min(item.planning.confidence for item in normalized_clauses),
            ),
            unresolved_questions=unresolved,
            evidence_limitations=list(evidence_limitations),
        )


def _global_prohibitions(
    clauses: Sequence[ClauseDecision],
) -> set[AbstractCapability]:
    prohibited: set[AbstractCapability] = set()
    for clause in clauses:
        prohibited.update(clause.prohibited_capabilities)
        if clause.external_information.external_information == "forbidden":
            prohibited.add("external_information")
        if clause.external_information.current_information == "forbidden":
            prohibited.add("current_information")
        if clause.existing_information.long_term_memory == "forbidden":
            prohibited.add("long_term_memory_read")
        if clause.memory_persistence.disposition == "forbidden":
            prohibited.add("memory_persistence")
        if clause.business_state.disposition == "forbidden":
            prohibited.add("business_state_change")
    return prohibited


def _apply_global_prohibitions(
    clause: ClauseDecision,
    prohibited: set[AbstractCapability],
) -> ClauseDecision:
    existing = clause.existing_information
    external = clause.external_information
    memory = clause.memory_persistence
    state = clause.business_state
    if "long_term_memory_read" in prohibited:
        existing = existing.model_copy(update={"long_term_memory": "forbidden"})
    if "external_information" in prohibited:
        external = external.model_copy(update={"external_information": "forbidden"})
    if "current_information" in prohibited:
        external = external.model_copy(update={"current_information": "forbidden"})
    if "memory_persistence" in prohibited:
        memory = memory.model_copy(update={"disposition": "forbidden"})
    if "business_state_change" in prohibited:
        state = state.model_copy(update={"disposition": "forbidden"})
    return clause.model_copy(
        update={
            "existing_information": existing,
            "external_information": external,
            "memory_persistence": memory,
            "business_state": state,
            "prohibited_capabilities": sorted(
                set(clause.prohibited_capabilities) | prohibited
            ),
        }
    )


def _unresolved_questions(clauses: Sequence[ClauseDecision]) -> list[str]:
    questions: list[str] = []
    for clause in clauses:
        questions.extend(clause.unresolved_questions)
        if clause.existing_information.conversation_context == "unknown":
            questions.append("需要明确“继续/类似”所指的上一主题。")
    return list(dict.fromkeys(questions))


def _conflict_questions(
    clauses: Sequence[ClauseDecision],
    prohibited: set[AbstractCapability],
) -> list[str]:
    questions: list[str] = []
    external_forbidden = (
        "external_information" in prohibited
        or "current_information" in prohibited
        or any(
        item.external_information.external_information == "forbidden"
        for item in clauses
        )
    )
    current_required = any(
        item.external_information.current_information == "required"
        for item in clauses
    )
    memory_read_forbidden = any(
        item.existing_information.long_term_memory == "forbidden"
        for item in clauses
    )
    personal_context_required = any(
        item.goal.kind == "retrieve_personal_context" for item in clauses
    )
    if external_forbidden and current_required:
        questions.append("请求同时禁止外部信息并要求当前信息，请确认优先约束。")
    if memory_read_forbidden and personal_context_required:
        questions.append("请求同时禁止读取长期记忆并要求回答个人历史，请确认优先约束。")
    return questions


def _aggregate_planning(
    clauses: Sequence[ClauseDecision],
    clarification: bool,
    prohibited: set[AbstractCapability],
) -> PlanningDecision:
    if clarification:
        return PlanningDecision(
            mode="clarification_required",
            rationale=["cross_axis_conflict_or_missing_context"],
            confidence=0.96,
        )
    modes = {item.planning.mode for item in clauses}
    if "decomposition" in prohibited and "decomposition_required" in modes:
        return PlanningDecision(
            mode="static_workflow",
            rationale=["decomposition_explicitly_forbidden"],
            confidence=0.95,
        )
    substantive = [
        item for item in clauses if item.goal.kind != "express_constraint"
    ]
    multi_workflow = (
        len(substantive) >= 2
        and any(item.planning.mode != "direct_answer" for item in substantive)
    )
    if "decomposition_required" in modes or len(clauses) >= 3 or multi_workflow:
        return PlanningDecision(
            mode="decomposition_required",
            rationale=["aggregate_multi_clause_planning"],
            confidence=0.94,
        )
    if "static_workflow" in modes:
        return PlanningDecision(
            mode="static_workflow",
            rationale=["aggregate_resolved_workflow"],
            confidence=0.91,
        )
    return PlanningDecision(
        mode="direct_answer",
        rationale=["aggregate_direct_answer"],
        confidence=0.92,
    )


def _is_substantive_direct_clause(clause: ClauseDecision) -> bool:
    return clause.planning.mode == "direct_answer"


def _limitations_affect_decision(
    clauses: Sequence[ClauseDecision],
) -> bool:
    """Degradation changes status only when a necessary axis is unresolved."""

    return any(
        clause.goal.confidence < 0.80
        or clause.existing_information.conversation_context == "unknown"
        or clause.memory_persistence.disposition == "uncertain"
        or clause.business_state.disposition == "uncertain"
        for clause in clauses
    )


def _dedupe_constraints(
    constraints: Sequence[DecisionConstraint],
) -> list[DecisionConstraint]:
    unique: dict[tuple[str, str, str], DecisionConstraint] = {}
    for constraint in constraints:
        key = (
            constraint.field,
            constraint.operator,
            repr(constraint.value),
        )
        unique.setdefault(key, constraint)
    return list(unique.values())
