"""Compile an InteractionDecision into business-only capability actions."""

from __future__ import annotations

from typing import Any

from app.services.routing.capabilities import (
    compile_book_actions,
    compile_conversation_actions,
    compile_external_actions,
    compile_memory_actions,
    compile_state_actions,
)
from app.services.routing.contracts import ProposedAction, RoutingRequirements
from app.services.routing.interaction_contracts import InteractionDecision


def compile_capability_actions(
    text: str,
    interaction: InteractionDecision,
    fast_path: Any | None = None,
) -> tuple[list[ProposedAction], RoutingRequirements]:
    """Project a resolved interaction into actions and legacy requirements.

    This is a compiler, not another classifier.  Capability admission is read
    exclusively from ``interaction``.  The raw text and optional fast-path
    result are passed to leaf compilers only for argument/slot extraction.
    """

    requirements = _compile_requirements(interaction)
    if interaction.status in {"clarification_required", "safe_default"}:
        return [], requirements

    actions = [
        *compile_conversation_actions(interaction),
        *compile_memory_actions(text, interaction, fast_path),
        *compile_external_actions(text, interaction, fast_path),
        *compile_book_actions(text, interaction, fast_path),
        *compile_state_actions(text, interaction, fast_path),
    ]
    actions = _wire_clause_dependencies(actions)
    _validate_unique_action_keys(actions)
    return actions, requirements


def _compile_requirements(
    interaction: InteractionDecision,
) -> RoutingRequirements:
    if interaction.status == "clarification_required":
        return RoutingRequirements(direct_answer_allowed=False)
    if interaction.status == "safe_default":
        return RoutingRequirements(
            direct_answer_allowed=interaction.direct_answer_allowed
        )
    global_prohibited = set(interaction.prohibited_capabilities)
    memory_read = False
    memory_write = False
    conversation_read = False
    weather = False
    external_search = False
    decomposition = interaction.planning.mode == "decomposition_required"

    for clause in interaction.clauses:
        prohibited = global_prohibited | set(clause.prohibited_capabilities)
        existing = clause.existing_information
        external = clause.external_information
        if (
            existing.conversation_context == "required"
            and clause.goal.kind == "recall_conversation"
            and "conversation_context" not in prohibited
        ):
            conversation_read = True
        if (
            existing.long_term_memory == "required"
            and "long_term_memory_read" not in prohibited
        ):
            memory_read = True
        if (
            clause.memory_persistence.disposition
            in {"candidate", "explicitly_requested"}
            and "memory_persistence" not in prohibited
        ):
            memory_write = True

        external_required = (
            external.external_information == "required"
            or external.current_information == "required"
        )
        external_allowed = not {
            "external_information",
            "current_information",
        }.intersection(prohibited)
        if external_required and external_allowed:
            external_search = True
            if (
                clause.goal.domain == "weather"
                and external.current_information == "required"
            ):
                weather = True
        if (
            clause.planning.mode == "decomposition_required"
            and "decomposition" not in prohibited
        ):
            decomposition = True

    return RoutingRequirements(
        direct_answer_allowed=interaction.direct_answer_allowed,
        conversation_read_required=conversation_read,
        memory_read_required=memory_read,
        memory_write_required=memory_write,
        weather_required=weather,
        external_search_required=external_search,
        decomposition_required=decomposition,
    )


def _wire_clause_dependencies(
    actions: list[ProposedAction],
) -> list[ProposedAction]:
    """Order recommendation search after same-clause context acquisition."""

    result: list[ProposedAction] = []
    for action in actions:
        if action.operation != "search_books":
            result.append(action)
            continue
        scope = _action_scope(action.action_key)
        dependencies = [
            candidate.action_key
            for candidate in actions
            if candidate.action_key != action.action_key
            and _action_scope(candidate.action_key) == scope
            and candidate.operation in {"search_memory", "web_search"}
        ]
        result.append(
            action.model_copy(
                update={
                    "depends_on": list(
                        dict.fromkeys([*action.depends_on, *dependencies])
                    )
                }
            )
        )
    return result


def _action_scope(action_key: str) -> str:
    if "__" not in action_key:
        return ""
    return action_key.split("__", 1)[0]


def _validate_unique_action_keys(actions: list[ProposedAction]) -> None:
    keys = [action.action_key for action in actions]
    duplicates = sorted({key for key in keys if keys.count(key) > 1})
    if duplicates:
        raise ValueError(
            "capability compiler produced duplicate action keys: "
            + ", ".join(duplicates)
        )
