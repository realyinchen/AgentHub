from __future__ import annotations

from app.services.research.search_policy import build_research_search_request
from app.services.routing.contracts import ProposedAction


def build_research_workflow(
    query: str,
    *,
    constraints: list[object] | None = None,
) -> list[ProposedAction]:
    """Build the bounded deep-research workflow for an admitted requirement.

    This module owns workflow topology only. It does not classify user text,
    execute providers, inject system fields, or write application state.
    """

    constraint_payload = [
        (
            item.model_dump(mode="json")
            if hasattr(item, "model_dump")
            else dict(item)
        )
        for item in (constraints or [])
    ]
    search_request = build_research_search_request(
        query,
        constraints=constraint_payload,
    )
    loop_budget = {
        "max_steps": 20,
        "max_search_rounds": 2,
        "max_results_per_round": search_request.max_results,
        "max_records_per_round": (
            min(search_request.max_results, 5)
            if "result_limit" in search_request.requirements
            else 3
        ),
        "max_sources": 6,
        "min_sources_per_claim": 1,
        "min_independent_sources": (
            2
            if (
                "review" in search_request.requirements
                and not search_request.include_domains
            )
            else 1
        ),
        "min_independent_sources_per_claim": 1,
        "required_evidence_quality": "medium",
    }
    actions = [
        ProposedAction(
            action_key="research_start",
            capability="research",
            operation="start_research",
            arguments={
                "objective": query,
                "mode": "deep_research",
                "subquestions": [query],
                "next_actions": [
                    "plan_search",
                    "acquire_sources",
                    "evaluate_gaps",
                    "repair_gaps",
                    "build_report",
                    "synthesize_answer",
                    "publish_answer",
                ],
                "budget": loop_budget,
                "stop_criteria": [
                    "verified_claims_ready",
                    "source_budget_exhausted",
                ],
                "metadata": {
                    "capture_source": "interaction_decision",
                    "research_loop_contract": "research-loop-v1",
                },
            },
            reason="Create app-owned research state before source acquisition.",
        ),
    ]
    previous_key = "research_start"
    for round_index in range(1, int(loop_budget["max_search_rounds"]) + 1):
        suffix = f"round_{round_index}"
        plan_key = f"research_plan_{suffix}"
        acquire_key = f"research_acquire_{suffix}"
        collect_key = f"research_collect_{suffix}"
        evidence_key = f"research_evidence_{suffix}"
        gaps_key = f"research_gaps_{suffix}"
        actions.extend(
            [
                ProposedAction(
                    action_key=plan_key,
                    capability="research",
                    operation="plan_research_search",
                    arguments={
                        "objective": query,
                        "round_index": round_index,
                        "budget": loop_budget,
                        "constraints": constraint_payload,
                    },
                    reason=(
                        "Compile one provider-neutral search task from the "
                        "current evidence gaps."
                    ),
                    depends_on=[previous_key],
                ),
                ProposedAction(
                    action_key=acquire_key,
                    capability="web",
                    operation="acquire_research_sources",
                    arguments={"round_index": round_index},
                    reason=(
                        "Execute the explicit search task only when the "
                        "research loop still has an unresolved gap."
                    ),
                    depends_on=[plan_key],
                ),
                ProposedAction(
                    action_key=collect_key,
                    capability="research",
                    operation="collect_research_sources",
                    arguments={
                        "round_index": round_index,
                        "metadata": {"capture_source": "research_loop"},
                    },
                    reason="Record normalized source observations for this round.",
                    depends_on=[acquire_key],
                ),
                ProposedAction(
                    action_key=evidence_key,
                    capability="research",
                    operation="add_evidence",
                    arguments={
                        "round_index": round_index,
                        "max_records": loop_budget["max_records_per_round"],
                        "metadata": {"capture_source": "research_loop"},
                    },
                    reason=(
                        "Pass this round's source records through evidence admission."
                    ),
                    depends_on=[collect_key],
                ),
                ProposedAction(
                    action_key=gaps_key,
                    capability="research",
                    operation="evaluate_research_gaps",
                    arguments={
                        "objective": query,
                        "round_index": round_index,
                        "budget": loop_budget,
                    },
                    reason=(
                        "Decide from admitted evidence whether another "
                        "bounded search round is required."
                    ),
                    depends_on=[evidence_key],
                ),
            ]
        )
        previous_key = gaps_key

    actions.extend(
        [
            ProposedAction(
                action_key="research_report",
                capability="research",
                operation="build_research_report",
                arguments={"limit_steps": 100, "limit_evidence": 100},
                reason="Build the report from admitted evidence.",
                depends_on=[previous_key],
            ),
            ProposedAction(
                action_key="research_synthesize",
                capability="research",
                operation="synthesize_research_answer",
                arguments={
                    "target_findings": (
                        min(search_request.max_results, 5)
                        if "result_limit" in search_request.requirements
                        else 0
                    )
                },
                reason=(
                    "Synthesize only admitted evidence into a constrained "
                    "ResearchBrief."
                ),
                depends_on=["research_report"],
            ),
            ProposedAction(
                action_key="research_publish",
                capability="research",
                operation="publish_research_answer",
                arguments={},
                reason="Render localized bounded Markdown from the validated brief.",
                depends_on=["research_synthesize"],
            ),
        ]
    )
    return actions
