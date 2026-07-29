"""Compile external-information and bounded research actions."""

from __future__ import annotations

from typing import Any

from app.services.planning.workflows import build_research_workflow
from app.services.research.query import normalize_research_query
from app.services.research.search_policy import build_research_search_request
from app.services.routing.capabilities import scoped_action_key, traced_reason
from app.services.routing.contracts import ProposedAction
from app.services.routing.interaction_contracts import (
    ClauseDecision,
    InteractionDecision,
)


def compile_external_actions(
    text: str,
    interaction: InteractionDecision,
    fast_path: Any | None = None,
) -> list[ProposedAction]:
    """Compile external calls selected by external/planning decision axes."""

    del text, fast_path
    actions: list[ProposedAction] = []
    clause_count = len(interaction.clauses)
    global_prohibited = set(interaction.prohibited_capabilities)

    for index, clause in enumerate(interaction.clauses):
        prohibited = global_prohibited | set(clause.prohibited_capabilities)
        external = clause.external_information
        external_required = (
            external.external_information == "required"
            or external.current_information == "required"
        )
        if not external_required or {
            "external_information",
            "current_information",
        }.intersection(prohibited):
            continue

        is_research = (
            clause.goal.kind == "research_topic"
            and clause.planning.mode == "decomposition_required"
        )
        if is_research:
            if "decomposition" in prohibited:
                continue
            actions.extend(
                _compile_research(
                    clause,
                    constraints=interaction.constraints,
                    clause_index=index,
                    clause_count=clause_count,
                )
            )
            continue

        search_request = build_research_search_request(
            clause.text,
            constraints=interaction.constraints,
        )
        weather = clause.goal.domain == "weather"
        actions.append(
            ProposedAction(
                action_key=scoped_action_key(
                    "web_lookup",
                    clause,
                    clause_index=index,
                    clause_count=clause_count,
                ),
                capability="web",
                operation="web_search",
                arguments={
                    "query": search_request.query,
                    "max_results": 3 if weather else 5,
                    "detail": "standard" if weather else "deep",
                    "time_range": search_request.time_range,
                    "include_domains": search_request.include_domains,
                    "exclude_domains": search_request.exclude_domains,
                    "include_url_prefixes": search_request.include_url_prefixes,
                    "language": search_request.language,
                },
                reason=traced_reason(
                    "Acquire the current or external information required by the decision.",
                    clause,
                ),
            )
        )
    return actions


def _compile_research(
    clause: ClauseDecision,
    *,
    constraints: list[object],
    clause_index: int,
    clause_count: int,
) -> list[ProposedAction]:
    query = normalize_research_query(clause.text)
    workflow = build_research_workflow(query, constraints=constraints)
    key_map = {
        action.action_key: scoped_action_key(
            action.action_key,
            clause,
            clause_index=clause_index,
            clause_count=clause_count,
        )
        for action in workflow
    }
    return [
        action.model_copy(
            update={
                "action_key": key_map[action.action_key],
                "depends_on": [key_map[key] for key in action.depends_on],
                "reason": traced_reason(action.reason, clause),
            }
        )
        for action in workflow
    ]
