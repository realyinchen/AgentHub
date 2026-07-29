"""Compile business-state changes selected by the state decision axis."""

from __future__ import annotations

from typing import Any

from app.services.books.feedback import extract_book_feedback
from app.services.routing.capabilities import scoped_action_key, traced_reason
from app.services.routing.contracts import ProposedAction
from app.services.routing.interaction_contracts import InteractionDecision


def compile_state_actions(
    text: str,
    interaction: InteractionDecision,
    fast_path: Any | None = None,
) -> list[ProposedAction]:
    """Compile supported state changes after authorization is already decided."""

    del text
    actions: list[ProposedAction] = []
    clause_count = len(interaction.clauses)
    global_prohibited = set(interaction.prohibited_capabilities)
    fast_feedback = _fast_path_feedback(fast_path) if clause_count == 1 else {}

    for index, clause in enumerate(interaction.clauses):
        prohibited = global_prohibited | set(clause.prohibited_capabilities)
        disposition = clause.business_state.disposition
        if (
            disposition not in {"proposed", "explicitly_requested"}
            or "business_state_change" in prohibited
            or clause.business_state.target not in {"book", "books"}
        ):
            continue

        # Parsing fills operation arguments only; an extraction hit never
        # authorizes the state-changing capability.
        feedback = fast_feedback or extract_book_feedback(clause.text)
        title = str(
            feedback.get("book_title")
            or (
                clause.goal.topic
                if str(clause.goal.topic or "").startswith("《")
                else ""
            )
        ).strip()
        if not title:
            continue
        actions.append(
            ProposedAction(
                action_key=scoped_action_key(
                    "record_book_feedback",
                    clause,
                    clause_index=index,
                    clause_count=clause_count,
                ),
                capability="book",
                operation="record_book_feedback",
                arguments={
                    "book_title": title,
                    "interaction_type": str(
                        feedback.get("interaction_type")
                        or feedback.get("event_type")
                        or "read"
                    ),
                    "note": clause.text,
                },
                reason=traced_reason(
                    "Apply the resolved, concrete book-state change.",
                    clause,
                ),
                required=disposition == "explicitly_requested",
            )
        )
    return actions


def _fast_path_feedback(fast_path: Any | None) -> dict[str, Any]:
    metadata = getattr(fast_path, "metadata", None)
    if not isinstance(metadata, dict):
        return {}
    feedback = metadata.get("feedback")
    return dict(feedback) if isinstance(feedback, dict) else {}
