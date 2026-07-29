from __future__ import annotations

import asyncio
from functools import lru_cache
from typing import Literal

from app.services.routing.capability_policy import compile_capability_actions
from app.services.routing.config import (
    AMBIGUITY_MARGIN,
    CANDIDATE_ADMISSION_THRESHOLD,
)
from app.services.routing.constraints import extract_routing_constraints
from app.services.routing.contracts import (
    IntentCandidate,
    RoutingConstraint,
    RoutingDecision,
    RoutingQuery,
)
from app.services.routing.decision_maker import InteractionDecisionMaker
from app.services.routing.execution_policy import compile_execution_policy
from app.services.routing.interaction_contracts import (
    InteractionDecision,
    InteractionDecisionInput,
    RecallBatch,
)
from app.services.routing.ports import RouterModelProvider, SemanticRecallProvider
from app.services.routing.rules import recall_rules
from app.services.routing.semantic import InMemorySemanticRecall


class RoutingFunnel:
    """Rules -> semantic recall -> optional model evidence -> decision."""

    def __init__(
        self,
        *,
        semantic_provider: SemanticRecallProvider | None = None,
        router_model_provider: RouterModelProvider | None = None,
    ) -> None:
        self._semantic = semantic_provider or InMemorySemanticRecall()
        self._router_model = router_model_provider

    async def warm_semantic_index(self) -> bool:
        warm = getattr(self._semantic, "warm", None)
        if warm is None:
            return False
        return bool(await warm())

    async def decide(self, query: RoutingQuery) -> RoutingDecision:
        rule_recall = recall_rules(query)
        candidates = list(rule_recall.candidates)
        layers = ["layer0_rule"]
        recall_batches: list[RecallBatch] = []

        # The latency invariant: a decisive Layer 0 result performs no semantic
        # network or vector work.
        if not rule_recall.decisive:
            recall_with_batches = getattr(
                self._semantic,
                "recall_with_batches",
                None,
            )
            if callable(recall_with_batches):
                semantic_candidates, recall_batches = await recall_with_batches(
                    query
                )
            else:
                semantic_candidates = await self._semantic.recall(query)
            candidates.extend(semantic_candidates)
            layers.append("layer1_keyword_vector")

        candidates = _ordered_candidates(candidates)
        constraints = extract_routing_constraints(query.text)
        interaction = _decide_interaction(
            query=query,
            candidates=candidates,
            constraints=constraints,
            recall_batches=recall_batches,
        )
        if (
            self._router_model is not None
            and not rule_recall.decisive
            and _needs_router_model(interaction)
        ):
            model_candidates = await self._router_model.classify(query)
            candidates.extend(
                item.model_copy(
                    update={
                        "source": "router_model",
                        "confidence": min(item.confidence, 0.95),
                    }
                )
                for item in model_candidates
            )
            candidates = _ordered_candidates(candidates)
            layers.append("layer2_router_model")
            interaction = _decide_interaction(
                query=query,
                candidates=candidates,
                constraints=constraints,
                recall_batches=recall_batches,
            )

        primary_intent = _legacy_primary_intent(interaction, candidates)
        confidence = interaction.confidence_by_axis.goal
        actions, requirements = compile_capability_actions(
            text=query.text,
            interaction=interaction,
            fast_path=rule_recall.fast_path,
        )
        planner_required = bool(
            interaction.planning.mode == "decomposition_required"
        )
        complexity = _complexity(
            action_count=len(actions),
            constraint_count=len(constraints),
            planner_required=planner_required,
        )
        route_type = (
            "fast_path"
            if (
                rule_recall.fast_path is not None
                or (not actions and complexity == "low")
            )
            else "slow_path"
        )
        policy = compile_execution_policy(
            primary_intent=primary_intent,
            candidates=candidates,
            actions=actions,
        )
        return RoutingDecision(
            intent_candidates=candidates,
            route_type=route_type,
            complexity=complexity,
            planner_required=planner_required,
            proposed_actions=actions,
            constraints=constraints,
            requirements=requirements,
            interaction_decision=interaction,
            primary_intent=primary_intent,
            confidence=confidence,
            policy=policy.model_dump(mode="json"),
            metadata={
                "decision_only": True,
                "executes_tools": False,
                "writes_memory": False,
                "layers_used": layers,
                "layer0_decisive": rule_recall.decisive,
                "router_model_enabled": self._router_model is not None,
                "interaction_decision_authoritative": True,
                "interaction_status": interaction.status,
                "recall_batches": [
                    item.model_dump(mode="json") for item in recall_batches
                ],
                "thresholds": {
                    "candidate_admission": CANDIDATE_ADMISSION_THRESHOLD,
                    "ambiguity_margin": AMBIGUITY_MARGIN,
                },
                **rule_recall.metadata,
            },
        )


def _needs_router_model(
    interaction: InteractionDecision,
) -> bool:
    return interaction.confidence_by_axis.goal < CANDIDATE_ADMISSION_THRESHOLD


def _decide_interaction(
    *,
    query: RoutingQuery,
    candidates: list[IntentCandidate],
    constraints: list[RoutingConstraint],
    recall_batches: list[RecallBatch],
) -> InteractionDecision:
    from app.services.routing.segmenter import segment_utterance

    clauses = segment_utterance(query.text)
    # Legacy candidates are whole-utterance hints without span provenance.
    # Applying them to every clause makes one capability word authorize all
    # clauses. Multi-clause decisions therefore rely on clause-local language
    # plus recall evidence that carries a matched span.
    scoped_candidates = candidates if len(clauses) == 1 else []
    request = InteractionDecisionInput.from_legacy_candidates(
        query.text,
        scoped_candidates,
        constraints=constraints,
        context=query.context,
    ).model_copy(
        update={
            "clauses": clauses,
            "recall_batches": recall_batches,
        }
    )
    return InteractionDecisionMaker().decide(request)


def _legacy_primary_intent(
    interaction: InteractionDecision,
    candidates: list[IntentCandidate],
) -> str:
    """Project orthogonal goals into the legacy single-intent compatibility field."""

    goal_kinds = [item.goal.kind for item in interaction.clauses]
    for kind, intent in (
        ("recall_conversation", "conversation_recall"),
        ("research_topic", "deep_research"),
        ("recommend_books", "recommend_books"),
        ("review_recommendation_history", "recommendation_history"),
        ("record_reading_feedback", "reading_feedback"),
        ("share_personal_information", "memory_update"),
        ("retrieve_personal_context", "memory_lookup"),
    ):
        if kind in goal_kinds:
            return intent
    if any(
        item.goal.domain == "weather"
        and item.external_information.current_information == "required"
        for item in interaction.clauses
    ):
        return "weather_lookup"
    if any(
        item.external_information.external_information == "required"
        or item.external_information.current_information == "required"
        for item in interaction.clauses
    ):
        return "external_lookup"
    if candidates:
        admitted = [
            item
            for item in candidates
            if item.confidence >= CANDIDATE_ADMISSION_THRESHOLD
            and item.intent == "answer_question"
        ]
        if admitted:
            return "answer_question"
    return "answer_question"


def _ordered_candidates(candidates: list[IntentCandidate]) -> list[IntentCandidate]:
    # Keep evidence from distinct sources visible. Only exact duplicate source /
    # intent pairs collapse.
    best: dict[tuple[str, str], IntentCandidate] = {}
    for candidate in candidates:
        key = (candidate.intent, candidate.source)
        current = best.get(key)
        if current is None or candidate.confidence > current.confidence:
            best[key] = candidate
        elif current is not None:
            best[key] = current.model_copy(
                update={"evidence": [*current.evidence, *candidate.evidence]}
            )
    return sorted(best.values(), key=lambda item: item.confidence, reverse=True)


def _complexity(
    *,
    action_count: int,
    constraint_count: int,
    planner_required: bool,
) -> Literal["low", "medium", "high"]:
    if planner_required:
        return "high"
    if action_count >= 2 or constraint_count >= 2:
        return "medium"
    return "low"


@lru_cache(maxsize=1)
def get_routing_funnel() -> RoutingFunnel:
    # Layer 2 is intentionally absent. A future model adapter is injected here
    # and still cannot bypass RoutingDecision or SystemRuntime.
    return RoutingFunnel()


_WARMUP_TASKS: set[asyncio.Task[None]] = set()


def schedule_routing_semantic_warmup() -> None:
    """Warm Layer 1 in the background without delaying application startup."""

    async def runner() -> None:
        await get_routing_funnel().warm_semantic_index()

    task = asyncio.create_task(runner(), name="routing-semantic-warmup")
    _WARMUP_TASKS.add(task)
    task.add_done_callback(_WARMUP_TASKS.discard)
