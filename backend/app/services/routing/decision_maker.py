from __future__ import annotations

from app.services.routing.business_state_resolver import BusinessStateResolver
from app.services.routing.capability_constraint_resolver import (
    CapabilityConstraintResolver,
)
from app.services.routing.conflict_resolver import DecisionConflictResolver
from app.services.routing.existing_information_resolver import (
    ExistingInformationResolver,
)
from app.services.routing.external_information_resolver import (
    ExternalInformationResolver,
)
from app.services.routing.goal_resolver import GoalResolver
from app.services.routing.interaction_contracts import (
    ClauseDecision,
    InteractionDecision,
    InteractionDecisionInput,
    evidence_for_clause,
)
from app.services.routing.memory_persistence_resolver import (
    MemoryPersistenceResolver,
)
from app.services.routing.planning_resolver import PlanningRequirementResolver
from app.services.routing.segmenter import UtteranceSegmenter


class InteractionDecisionMaker:
    """Coordinate pure axis resolvers; never compile or execute an action."""

    def __init__(
        self,
        *,
        segmenter: UtteranceSegmenter | None = None,
        goal_resolver: GoalResolver | None = None,
        existing_information_resolver: ExistingInformationResolver | None = None,
        external_information_resolver: ExternalInformationResolver | None = None,
        memory_persistence_resolver: MemoryPersistenceResolver | None = None,
        business_state_resolver: BusinessStateResolver | None = None,
        planning_resolver: PlanningRequirementResolver | None = None,
        conflict_resolver: DecisionConflictResolver | None = None,
        capability_constraint_resolver: CapabilityConstraintResolver | None = None,
    ) -> None:
        self._segmenter = segmenter or UtteranceSegmenter()
        self._goal = goal_resolver or GoalResolver()
        self._existing = (
            existing_information_resolver or ExistingInformationResolver()
        )
        self._external = (
            external_information_resolver or ExternalInformationResolver()
        )
        self._memory = memory_persistence_resolver or MemoryPersistenceResolver()
        self._state = business_state_resolver or BusinessStateResolver()
        self._planning = planning_resolver or PlanningRequirementResolver()
        self._conflicts = conflict_resolver or DecisionConflictResolver()
        self._capability_constraints = (
            capability_constraint_resolver or CapabilityConstraintResolver()
        )

    def decide(self, request: InteractionDecisionInput) -> InteractionDecision:
        clauses = request.clauses or self._segmenter.segment(request.text)
        all_evidence = request.all_evidence()
        clause_decisions: list[ClauseDecision] = []

        for clause in clauses:
            evidence = evidence_for_clause(all_evidence, clause)
            goal = self._goal.resolve(clause, evidence, request.context)
            existing = self._existing.resolve(
                clause,
                goal,
                evidence,
                request.context,
            )
            external = self._external.resolve(clause, goal, evidence)
            memory = self._memory.resolve(
                clause,
                goal,
                evidence,
                request.context,
            )
            state = self._state.resolve(clause, goal, evidence)
            planning = self._planning.resolve(
                clause=clause,
                goal=goal,
                existing=existing,
                external=external,
                memory=memory,
                state=state,
                clause_count=len(clauses),
            )
            prohibited = self._capability_constraints.resolve(clause)
            if existing.long_term_memory == "forbidden":
                prohibited.append("long_term_memory_read")
            if external.external_information == "forbidden":
                prohibited.append("external_information")
            if external.current_information == "forbidden":
                prohibited.append("current_information")
            if memory.disposition == "forbidden":
                prohibited.append("memory_persistence")
            if state.disposition == "forbidden":
                prohibited.append("business_state_change")

            clause_decisions.append(
                ClauseDecision(
                    clause_id=clause.clause_id,
                    text=clause.text,
                    goal=goal,
                    existing_information=existing,
                    external_information=external,
                    memory_persistence=memory,
                    business_state=state,
                    planning=planning,
                    prohibited_capabilities=prohibited,
                )
            )

        constraints = [
            *request.context.previous_constraints,
            *request.constraints,
        ]
        return self._conflicts.resolve(
            clauses=clause_decisions,
            constraints=constraints,
            evidence_limitations=request.incomplete_evidence_reasons(),
        )


def decide_interaction(request: InteractionDecisionInput) -> InteractionDecision:
    return InteractionDecisionMaker().decide(request)
