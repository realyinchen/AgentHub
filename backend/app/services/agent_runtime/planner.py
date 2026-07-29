from __future__ import annotations

from app.schemas.chat import UserInput
from app.services.agent_runtime.contracts import ActionPlan
from app.services.planning.compiler import compile_action_plan
from app.services.routing import RoutingQuery, get_routing_funnel
from app.services.routing.context import routing_text
from app.services.routing.interaction_contracts import BusinessRoutingContext


class ActionPlanner:
    """Single entry: RoutingDecision -> ActionPlan.

    The selected chat model is intentionally irrelevant to routing while the
    optional Layer 2 provider is disabled.
    """

    async def plan(
        self,
        user_input: UserInput,
        *,
        model_name: str = "",
        routing_context: BusinessRoutingContext | None = None,
    ) -> ActionPlan:
        del model_name
        query_text = routing_text(user_input)
        decision = await get_routing_funnel().decide(
            RoutingQuery(
                text=query_text,
                context=routing_context or BusinessRoutingContext(),
            )
        )
        return compile_action_plan(decision, goal=user_input.content)


def build_fast_action_plan(user_input: UserInput) -> ActionPlan | None:
    """Compatibility helper backed by the new contract, with no execution."""

    from app.services.routing.capability_policy import compile_capability_actions
    from app.services.routing.constraints import extract_routing_constraints
    from app.services.routing.contracts import RoutingDecision
    from app.services.routing.decision_maker import InteractionDecisionMaker
    from app.services.routing.execution_policy import compile_execution_policy
    from app.services.routing.interaction_contracts import InteractionDecisionInput
    from app.services.routing.rules import recall_rules

    query = RoutingQuery(text=routing_text(user_input))
    recall = recall_rules(query)
    if recall.fast_path is None or not recall.candidates:
        return None
    constraints = extract_routing_constraints(query.text)
    interaction = InteractionDecisionMaker().decide(
        InteractionDecisionInput.from_legacy_candidates(
            query.text,
            recall.candidates,
            constraints=constraints,
        )
    )
    actions, requirements = compile_capability_actions(
        text=query.text,
        interaction=interaction,
        fast_path=recall.fast_path,
    )
    primary_intent = _compat_primary_intent(interaction)
    decision = RoutingDecision(
        intent_candidates=recall.candidates,
        route_type="fast_path",
        complexity="low",
        planner_required=False,
        proposed_actions=actions,
        constraints=constraints,
        requirements=requirements,
        interaction_decision=interaction,
        primary_intent=primary_intent,
        confidence=interaction.confidence_by_axis.goal,
        policy=compile_execution_policy(
            primary_intent=primary_intent,
            candidates=recall.candidates,
            actions=actions,
        ).model_dump(mode="json"),
        metadata={
            "decision_only": True,
            "layer0_decisive": True,
            "interaction_decision_authoritative": True,
            **recall.metadata,
        },
    )
    return compile_action_plan(decision, goal=query.text)


def _compat_primary_intent(
    interaction: "InteractionDecision",
) -> str:
    """Project the orthogonal decision into the legacy display field only."""

    from app.services.routing.interaction_contracts import InteractionDecision

    if not isinstance(interaction, InteractionDecision):
        raise TypeError("interaction must be an InteractionDecision")
    goal_kinds = {clause.goal.kind for clause in interaction.clauses}
    for goal, intent in (
        ("record_reading_feedback", "reading_feedback"),
        ("share_personal_information", "memory_update"),
        ("retrieve_personal_context", "memory_lookup"),
        ("recommend_books", "recommend_books"),
        ("research_topic", "deep_research"),
    ):
        if goal in goal_kinds:
            return intent
    return "answer_question"
