"""Compile durable-memory reads and persistence proposals."""

from __future__ import annotations

import re
from typing import Any

from app.services.routing.capabilities import scoped_action_key, traced_reason
from app.services.routing.contracts import ProposedAction
from app.services.routing.interaction_contracts import (
    ClauseDecision,
    InteractionDecision,
)
from app.services.memory.write_contracts import (
    MemoryClarificationContext,
    MemoryWriteRequest,
)


_NAME_LOOKUP_RE = re.compile(
    r"(?:我是谁|我叫(?:什么|啥)|我的名字(?:是什么)?|"
    r"who\s+am\s+i|what(?:'s|\s+is)\s+my\s+name)",
    re.IGNORECASE,
)
_PET_COUNT_LOOKUP_RE = re.compile(
    r"(?:我有(?:多少|几只)宠物|我有哪些宠物|"
    r"how\s+many\s+pets?\s+do\s+i\s+have)",
    re.IGNORECASE,
)
_PET_LOOKUP_RE = re.compile(
    r"(?:我的(?:猫|猫咪|狗|狗狗|宠物)|my\s+(?:cat|dog|pet))",
    re.IGNORECASE,
)


def compile_memory_actions(
    text: str,
    interaction: InteractionDecision,
    fast_path: Any | None = None,
) -> list[ProposedAction]:
    """Compile memory actions selected by InteractionDecision axes.

    ``text`` and ``fast_path`` are used only to fill lookup/capture slots.
    Neither may enable a read or a write.
    """

    del text
    actions: list[ProposedAction] = []
    clause_count = len(interaction.clauses)
    global_prohibited = set(interaction.prohibited_capabilities)

    for index, clause in enumerate(interaction.clauses):
        clause_fast_path = fast_path if clause_count == 1 else None
        prohibited = global_prohibited | set(clause.prohibited_capabilities)
        memory_level = clause.existing_information.long_term_memory
        if (
            memory_level in {"required", "optional"}
            and "long_term_memory_read" not in prohibited
        ):
            actions.append(
                _compile_memory_read(
                    clause,
                    fast_path=clause_fast_path,
                    required=memory_level == "required",
                    clause_index=index,
                    clause_count=clause_count,
                )
            )

        persistence = clause.memory_persistence.disposition
        if (
            persistence in {"candidate", "explicitly_requested"}
            and "memory_persistence" not in prohibited
        ):
            actions.append(
                _compile_memory_capture(
                    clause,
                    fast_path=clause_fast_path,
                    required=persistence == "explicitly_requested",
                    clause_index=index,
                    clause_count=clause_count,
                )
            )
    return actions


def _compile_memory_read(
    clause: ClauseDecision,
    *,
    fast_path: Any | None,
    required: bool,
    clause_index: int,
    clause_count: int,
) -> ProposedAction:
    metadata = _fast_path_metadata(fast_path)
    lookup_kind, query = _lookup_slots(clause, metadata)
    recommendation_context = clause.goal.kind == "recommend_books"
    arguments: dict[str, Any] = {
        "query": query,
        "lookup_kind": (
            "recommendation_context" if recommendation_context else lookup_kind
        ),
        "limit": 10 if recommendation_context else 50,
    }
    if recommendation_context:
        arguments["memory_types"] = [
            "preference",
            "reading_state",
            "feedback",
            "correction",
        ]
    return ProposedAction(
        action_key=scoped_action_key(
            "read_preferences" if recommendation_context else "read_memory",
            clause,
            clause_index=clause_index,
            clause_count=clause_count,
        ),
        capability="memory",
        operation="search_memory",
        arguments=arguments,
        reason=traced_reason(
            (
                "Read optional durable preference context for personalization."
                if recommendation_context
                else "Read durable personal context required by the decision."
            ),
            clause,
        ),
        required=required,
    )


def _compile_memory_capture(
    clause: ClauseDecision,
    *,
    fast_path: Any | None,
    required: bool,
    clause_index: int,
    clause_count: int,
) -> ProposedAction:
    del fast_path
    persistence = clause.memory_persistence
    request = MemoryWriteRequest(
        operation=persistence.operation or "create",
        utterance=clause.text,
        target_expression=str(
            persistence.target_expression or persistence.subject or ""
        ),
        explicit=(
            persistence.explicit
            or persistence.disposition == "explicitly_requested"
        ),
        conversation_context_required=persistence.conversation_context_required,
        clarification=(
            MemoryClarificationContext.model_validate(
                persistence.pending_clarification.model_dump(mode="json")
            )
            if persistence.pending_clarification is not None
            else None
        ),
    )
    return ProposedAction(
        action_key=scoped_action_key(
            "process_memory_write",
            clause,
            clause_index=clause_index,
            clause_count=clause_count,
        ),
        capability="memory",
        operation="process_memory_write_request",
        arguments={"request": request.model_dump(mode="json")},
        reason=traced_reason(
            "Resolve, validate, conflict-check, and only then commit durable memory.",
            clause,
        ),
        required=required,
    )


def _lookup_slots(
    clause: ClauseDecision,
    fast_metadata: dict[str, Any],
) -> tuple[str, str]:
    """Extract lookup parameters after the read capability is already selected."""

    metadata_kind = str(fast_metadata.get("lookup_kind") or "").strip()
    metadata_query = str(fast_metadata.get("query") or "").strip()
    if metadata_kind:
        return metadata_kind, metadata_query

    text = clause.text.strip()
    if _NAME_LOOKUP_RE.search(text):
        return "name", ""
    if _PET_COUNT_LOOKUP_RE.search(text):
        return "pet_count", ""
    if _PET_LOOKUP_RE.search(text):
        return "pet", ""
    return "generic", text


def _fast_path_metadata(fast_path: Any | None) -> dict[str, Any]:
    value = getattr(fast_path, "metadata", None)
    return dict(value) if isinstance(value, dict) else {}
