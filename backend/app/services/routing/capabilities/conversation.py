"""Compile current-thread conversation reads."""

from __future__ import annotations

from app.services.routing.capabilities import scoped_action_key, traced_reason
from app.services.routing.contracts import ProposedAction
from app.services.routing.interaction_contracts import InteractionDecision


def compile_conversation_actions(
    interaction: InteractionDecision,
) -> list[ProposedAction]:
    actions: list[ProposedAction] = []
    clause_count = len(interaction.clauses)
    global_prohibited = set(interaction.prohibited_capabilities)
    for index, clause in enumerate(interaction.clauses):
        prohibited = global_prohibited | set(clause.prohibited_capabilities)
        if (
            clause.goal.kind != "recall_conversation"
            or clause.existing_information.conversation_context != "required"
            or "conversation_context" in prohibited
        ):
            continue
        actions.append(
            ProposedAction(
                action_key=scoped_action_key(
                    "recall_conversation",
                    clause,
                    clause_index=index,
                    clause_count=clause_count,
                ),
                capability="conversation",
                operation="recall_recent_conversation",
                arguments={"query": clause.text, "limit": 4},
                reason=traced_reason(
                    "Read recent messages from the current thread only.",
                    clause,
                ),
                required=True,
            )
        )
    return actions
