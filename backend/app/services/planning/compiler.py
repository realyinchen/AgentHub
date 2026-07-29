from __future__ import annotations

from typing import Literal

from app.services.agent_runtime.contracts import ActionPlan, PlannedAction
from app.services.routing.contracts import RoutingDecision


def compile_action_plan(decision: RoutingDecision, *, goal: str) -> ActionPlan:
    """Compile one RoutingDecision into the only executable plan contract."""

    provisional = [
        PlannedAction(
            capability=proposal.capability,
            operation=proposal.operation,
            arguments=proposal.arguments,
            reason=proposal.reason,
            required=proposal.required,
            metadata={"routing_action_key": proposal.action_key},
        )
        for proposal in decision.proposed_actions
    ]
    ids_by_key = {
        proposal.action_key: action.action_id
        for proposal, action in zip(
            decision.proposed_actions,
            provisional,
            strict=True,
        )
    }
    actions = [
        action.model_copy(
            update={
                "depends_on": [
                    ids_by_key[key]
                    for key in proposal.depends_on
                    if key in ids_by_key
                ]
            }
        )
        for proposal, action in zip(
            decision.proposed_actions,
            provisional,
            strict=True,
        )
    ]
    return ActionPlan(
        source="routing_decision",
        route_type=decision.route_type,
        intent=decision.primary_intent,
        goal=goal,
        confidence=decision.confidence,
        complexity=decision.complexity,
        planner_used=False,
        response_mode=_response_mode(decision),
        actions=actions,
        forbidden_operations=list(decision.policy.get("denied_tools") or []),
        policy=decision.policy,
        metadata={
            "decision_only": True,
            "planner_required": decision.planner_required,
            "planning_strategy": (
                "explicit_runtime_search_tasks"
                if any(
                    action.operation == "plan_research_search"
                    for action in actions
                )
                else "deterministic_compiler"
            ),
            "routing_contract_version": decision.contract_version,
            "routing_decision": decision.model_dump(mode="json"),
        },
    )


def _response_mode(
    decision: RoutingDecision,
) -> Literal["deterministic", "receipt", "model"]:
    operations = {action.operation for action in decision.proposed_actions}
    if operations.intersection(
        {"publish_research_answer", "finalize_research_answer"}
    ):
        return "receipt"
    if operations.intersection(
        {
            "recall_recent_conversation",
            "search_memory",
            "process_memory_write_request",
            "record_book_feedback",
            "record_recommendation_signal",
        }
    ) and operations.issubset(
        {
            "recall_recent_conversation",
            "search_memory",
            "process_memory_write_request",
            "record_book_feedback",
            "record_recommendation_signal",
        }
    ):
        return "deterministic"
    return "model"
