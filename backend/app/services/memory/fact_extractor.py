from __future__ import annotations

from typing import Any

from app.schemas.chat import UserInput
from app.services.memory.semantic_interpreter import interpret_user_state
from app.services.memory.schema_registry import (
    canonical_state_key,
    is_canonical_state_key,
)
from app.services.memory.write_contracts import (
    MemoryFactDraft,
    MemoryReferenceResolution,
)
from app.services.profile_memory_capture import (
    extract_explicit_profile_memory_candidates,
)


class MemoryFactExtractor:
    """Extract typed drafts from one resolved user-authored source."""

    def deterministic(
        self,
        *,
        user_input: UserInput,
        resolution: MemoryReferenceResolution,
    ) -> list[MemoryFactDraft]:
        if resolution.source is None:
            return []
        source_input = user_input.model_copy(
            update={"content": resolution.resolved_text}
        )
        candidates = extract_explicit_profile_memory_candidates(source_input)
        return [
            _draft_from_candidate(candidate, resolution)
            for candidate in candidates
        ]

    async def semantic(
        self,
        *,
        resolution: MemoryReferenceResolution,
        model_id: str,
    ) -> MemoryFactDraft:
        if resolution.source is None:
            raise ValueError("semantic extraction requires resolved user source")
        proposal = await interpret_user_state(
            resolution.resolved_text,
            requested_model_id=model_id,
        )
        state_key = _normalized_state_key(proposal.category, proposal.state_key)
        legacy_type, legacy_subject, polarity = _legacy_projection(
            proposal.category,
            proposal.state_value,
        )
        legacy_value = _legacy_value(state_key, proposal.summary, proposal.state_value)
        unresolved = []
        if proposal.needs_confirmation:
            unresolved.append("semantic_interpreter_requires_confirmation")
        return MemoryFactDraft(
            category=proposal.category,
            state_key=state_key,
            summary=proposal.summary,
            state_value=proposal.state_value,
            relation=proposal.relation,
            use_when=proposal.use_when,
            legacy_type=legacy_type,
            legacy_subject=legacy_subject,
            legacy_value=legacy_value,
            polarity=polarity,
            durability=(
                "short_term"
                if proposal.category == "short_term"
                else "long_term"
            ),
            source=resolution.source,
            extraction_method="semantic",
            extraction_confidence=proposal.confidence,
            unresolved_references=unresolved,
            clarification_question=proposal.confirmation_question,
        )


def _draft_from_candidate(
    candidate: Any,
    resolution: MemoryReferenceResolution,
) -> MemoryFactDraft:
    metadata = dict(candidate.metadata or {})
    user_state = dict(metadata.get("user_state") or {})
    category = str(user_state.get("category") or "")
    state_key = str(user_state.get("state_key") or "")
    state_value = (
        user_state.get("state_value")
        if isinstance(user_state.get("state_value"), dict)
        else {}
    )
    summary = str(user_state.get("summary") or candidate.value)
    if state_key == "profile.name" and str(state_value.get("name") or "").strip():
        summary = f"你的名字是{str(state_value['name']).strip()}"
    return MemoryFactDraft(
        category=category,
        state_key=state_key,
        summary=summary,
        state_value=state_value,
        relation=(
            user_state.get("relation")
            if isinstance(user_state.get("relation"), dict)
            else {}
        ),
        use_when=(
            user_state.get("use_when")
            if isinstance(user_state.get("use_when"), list)
            else []
        ),
        legacy_type=candidate.type,
        legacy_subject=candidate.subject,
        legacy_value=candidate.value,
        polarity=candidate.polarity,
        durability="long_term",
        source=resolution.source,
        extraction_method="deterministic",
        extraction_confidence=candidate.confidence,
    )


def _normalized_state_key(category: str, state_key: str) -> str:
    key = str(state_key or "").strip().lower().replace(" ", "_")
    if not key:
        return ""
    if is_canonical_state_key(key, category=category):
        return key
    return canonical_state_key(category, key)


def _legacy_projection(
    category: str,
    state_value: dict[str, Any],
) -> tuple[str, str, str]:
    if category == "profile":
        return "preference", "user", "neutral"
    if category == "preference":
        polarity = str(state_value.get("polarity") or "neutral")
        if polarity not in {"like", "dislike", "neutral", "want", "avoid"}:
            polarity = "neutral"
        return "preference", "user", polarity
    if category == "relation":
        return "entity", "entity", "neutral"
    if category == "feedback":
        return "feedback", "user", "neutral"
    return "state", "user", "neutral"


def _legacy_value(
    state_key: str,
    summary: str,
    state_value: dict[str, Any],
) -> str:
    if state_key == "profile.name":
        name = str(state_value.get("name") or "").strip()
        if name:
            return f"name: {name}"
    return str(summary or "").strip()
