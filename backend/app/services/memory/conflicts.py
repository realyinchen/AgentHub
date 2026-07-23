from __future__ import annotations

import re
from typing import Iterable
from uuid import UUID

from app.services.memory.contracts import (
    MemoryCandidate,
    MemoryConflict,
    MemoryConflictResolution,
    MemoryEvent,
    normalize_memory_value,
)


POSITIVE_POLARITIES = frozenset({"like", "want", "read"})
NEGATIVE_POLARITIES = frozenset({"dislike", "avoid"})
READING_PROGRESSIONS = frozenset({("want", "read")})
CORRECTION_MARKERS = frozenset(
    {
        "actually",
        "instead",
        "rather",
        "correction",
        "correct",
        "i meant",
        "not",
        "just not",
        "只是",
        "不是",
        "其实",
        "准确",
        "更准确",
        "纠正",
        "不是说",
        "而是",
    }
)
TOKEN_STOPWORDS = frozenset(
    {
        "a",
        "an",
        "and",
        "are",
        "but",
        "for",
        "i",
        "is",
        "just",
        "like",
        "not",
        "or",
        "rather",
        "the",
        "too",
        "want",
        "with",
    }
)


class MemoryConflictResolver:
    """Resolve admitted candidates against active app-owned memories."""

    def resolve(
        self,
        candidate: MemoryCandidate,
        current_memories: Iterable[MemoryEvent],
    ) -> MemoryConflictResolution:
        active = [
            memory
            for memory in current_memories
            if not memory.forgotten and memory.superseded_by is None
        ]
        duplicate = self._find_duplicate(candidate, active)
        if duplicate is not None:
            return self._resolution(
                "skip_duplicate",
                "duplicate_current_memory",
                candidate,
                duplicate,
                self._conflict(
                    "duplicate",
                    candidate,
                    duplicate,
                    "low",
                    "skip_duplicate",
                    "same current memory already exists",
                ),
            )

        profile_key_target = self._find_profile_key_update(candidate, active)
        if profile_key_target is not None:
            return self._resolution(
                "revise_existing",
                "profile_key_update",
                candidate,
                profile_key_target,
                self._conflict(
                    "explicit_correction",
                    candidate,
                    profile_key_target,
                    "medium",
                    "revise_existing",
                    "same user profile key should keep one current value",
                ),
            )

        state_progression = self._find_state_progression(candidate, active)
        if state_progression is not None:
            return self._resolution(
                "revise_existing",
                "reading_state_progression",
                candidate,
                state_progression,
                self._conflict(
                    "state_progression",
                    candidate,
                    state_progression,
                    "low",
                    "revise_existing",
                    "reading state progressed from want to read",
                ),
            )

        direct_conflict = self._find_direct_polarity_conflict(candidate, active)
        if direct_conflict is not None:
            return self._resolution(
                "revise_existing",
                "direct_polarity_conflict",
                candidate,
                direct_conflict,
                self._conflict(
                    "direct_polarity_conflict",
                    candidate,
                    direct_conflict,
                    "high",
                    "revise_existing",
                    "same memory key has opposite polarity",
                ),
            )

        correction_target = self._find_explicit_correction_target(candidate, active)
        if correction_target == "ambiguous":
            return self._ambiguous(candidate, "explicit_correction_target_ambiguous")
        if isinstance(correction_target, MemoryEvent):
            return self._resolution(
                "revise_existing",
                "explicit_correction",
                candidate,
                correction_target,
                self._conflict(
                    "explicit_correction",
                    candidate,
                    correction_target,
                    "high",
                    "revise_existing",
                    "candidate is an explicit correction of current memory",
                ),
            )

        refinement_target = self._find_preference_refinement(candidate, active)
        if refinement_target == "ambiguous":
            return self._ambiguous(candidate, "preference_refinement_ambiguous")
        if isinstance(refinement_target, MemoryEvent):
            return self._resolution(
                "revise_existing",
                "preference_refinement",
                candidate,
                refinement_target,
                self._conflict(
                    "preference_refinement",
                    candidate,
                    refinement_target,
                    "medium",
                    "revise_existing",
                    "candidate refines a broader current preference",
                ),
            )

        ambiguous = self._find_ambiguous_conflict(candidate, active)
        if ambiguous is not None:
            return self._resolution(
                "needs_confirmation",
                "ambiguous_memory_conflict",
                candidate,
                ambiguous,
                self._conflict(
                    "ambiguous_conflict",
                    candidate,
                    ambiguous,
                    "medium",
                    "needs_confirmation",
                    "candidate overlaps current memory but conflict is unclear",
                ),
            )

        return MemoryConflictResolution(
            decision="allow",
            reason="no_conflict",
            candidate=candidate,
        )

    def _find_duplicate(
        self,
        candidate: MemoryCandidate,
        memories: list[MemoryEvent],
    ) -> MemoryEvent | None:
        for memory in memories:
            if (
                memory.type == candidate.type
                and memory.subject == candidate.subject
                and _same_value(memory.value, candidate.value)
                and memory.polarity == candidate.polarity
            ):
                return memory
        return None

    def _find_profile_key_update(
        self,
        candidate: MemoryCandidate,
        memories: list[MemoryEvent],
    ) -> MemoryEvent | None:
        key = _profile_key(candidate)
        if not key:
            return None
        for memory in memories:
            if (
                memory.type == candidate.type
                and memory.subject == candidate.subject
                and _profile_key(memory) == key
                and not _same_value(memory.value, candidate.value)
            ):
                return memory
        return None

    def _find_state_progression(
        self,
        candidate: MemoryCandidate,
        memories: list[MemoryEvent],
    ) -> MemoryEvent | None:
        if candidate.type != "reading_state" or candidate.subject != "book":
            return None
        for memory in memories:
            if (
                memory.type == "reading_state"
                and memory.subject == "book"
                and _same_value(memory.value, candidate.value)
                and (memory.polarity, candidate.polarity) in READING_PROGRESSIONS
            ):
                return memory
        return None

    def _find_direct_polarity_conflict(
        self,
        candidate: MemoryCandidate,
        memories: list[MemoryEvent],
    ) -> MemoryEvent | None:
        for memory in memories:
            if (
                memory.type == candidate.type
                and memory.subject == candidate.subject
                and _same_value(memory.value, candidate.value)
                and _opposite_polarity(memory.polarity, candidate.polarity)
            ):
                return memory
        return None

    def _find_explicit_correction_target(
        self,
        candidate: MemoryCandidate,
        memories: list[MemoryEvent],
    ) -> MemoryEvent | str | None:
        if not self._is_explicit_correction(candidate):
            return None
        matches = [
            memory
            for memory in memories
            if self._correction_target_score(candidate, memory) > 0
        ]
        return self._single_or_ambiguous(matches)

    def _find_preference_refinement(
        self,
        candidate: MemoryCandidate,
        memories: list[MemoryEvent],
    ) -> MemoryEvent | str | None:
        if not self._is_explicit_correction(candidate):
            return None
        if candidate.type not in {"preference", "correction"}:
            return None
        matches = [
            memory
            for memory in memories
            if memory.type in {"preference", "correction"}
            and memory.subject == candidate.subject
            and _same_polarity_family(memory.polarity, candidate.polarity)
            and _is_more_specific(candidate.value, memory.value)
        ]
        return self._single_or_ambiguous(matches)

    def _find_ambiguous_conflict(
        self,
        candidate: MemoryCandidate,
        memories: list[MemoryEvent],
    ) -> MemoryEvent | None:
        for memory in memories:
            if memory.type != candidate.type or memory.subject != candidate.subject:
                continue
            if not _opposite_polarity(memory.polarity, candidate.polarity):
                continue
            if _same_value(memory.value, candidate.value):
                continue
            if _values_overlap(memory.value, candidate.value) and not _is_more_specific(
                candidate.value,
                memory.value,
            ):
                return memory
        return None

    def _is_explicit_correction(self, candidate: MemoryCandidate) -> bool:
        if candidate.type == "correction":
            return True
        metadata = candidate.metadata
        if metadata.get("explicit_correction") is True:
            return True
        if metadata.get("correction"):
            return True
        text = f"{candidate.source_text} {metadata.get('note', '')}".lower()
        return any(marker in text for marker in CORRECTION_MARKERS)

    def _correction_target_score(
        self,
        candidate: MemoryCandidate,
        memory: MemoryEvent,
    ) -> int:
        score = 0
        source_text = candidate.source_text.lower()
        value_signal = 0
        if _same_value(memory.value, candidate.value):
            value_signal += 4
        if _values_overlap(memory.value, candidate.value):
            value_signal += 2
        if memory.value.strip().lower() and memory.value.strip().lower() in source_text:
            value_signal += 3
        if value_signal == 0:
            return 0
        score += value_signal
        if memory.type == candidate.type or candidate.type == "correction":
            score += 1
        if memory.subject == candidate.subject:
            score += 2
        if _opposite_polarity(memory.polarity, candidate.polarity):
            score += 1
        return score

    def _single_or_ambiguous(
        self,
        matches: list[MemoryEvent],
    ) -> MemoryEvent | str | None:
        unique = {memory.id: memory for memory in matches if memory.id is not None}
        if len(unique) == 1:
            return next(iter(unique.values()))
        if len(unique) > 1:
            return "ambiguous"
        return None

    def _ambiguous(
        self,
        candidate: MemoryCandidate,
        reason: str,
    ) -> MemoryConflictResolution:
        conflict = MemoryConflict(
            conflict_type="ambiguous_conflict",
            existing_memory_id=None,
            candidate=candidate,
            severity="medium",
            suggested_decision="needs_confirmation",
            reason=reason,
        )
        return MemoryConflictResolution(
            decision="needs_confirmation",
            reason=reason,
            candidate=candidate,
            conflicts=[conflict],
        )

    def _resolution(
        self,
        decision: str,
        reason: str,
        candidate: MemoryCandidate,
        target: MemoryEvent,
        conflict: MemoryConflict,
    ) -> MemoryConflictResolution:
        return MemoryConflictResolution(
            decision=decision,
            reason=reason,
            candidate=candidate,
            target_memory_id=target.id,
            conflicts=[conflict],
        )

    def _conflict(
        self,
        conflict_type: str,
        candidate: MemoryCandidate,
        existing: MemoryEvent,
        severity: str,
        suggested_decision: str,
        reason: str,
    ) -> MemoryConflict:
        return MemoryConflict(
            conflict_type=conflict_type,
            existing_memory_id=existing.id,
            candidate=candidate,
            severity=severity,
            suggested_decision=suggested_decision,
            reason=reason,
            metadata={
                "existing_type": existing.type,
                "existing_subject": existing.subject,
                "existing_value": existing.value,
                "existing_polarity": existing.polarity,
            },
        )


def _same_value(left: str, right: str) -> bool:
    return _canonical(left) == _canonical(right)


def _profile_key(memory: MemoryCandidate | MemoryEvent) -> str:
    metadata = memory.metadata or {}
    key = str(metadata.get("profile_key") or "").strip().lower()
    if key:
        return key
    value = normalize_memory_value(memory.value).lower()
    if value.startswith("name:"):
        return "name"
    if value.startswith("sleep routine:"):
        return "sleep_routine"
    return ""


def _canonical(value: str) -> str:
    return re.sub(r"\s+", " ", normalize_memory_value(value).lower()).strip()


def _tokens(value: str) -> set[str]:
    raw = re.findall(r"[\w\u4e00-\u9fff]+", normalize_memory_value(value).lower())
    return {item for item in raw if len(item) > 1 and item not in TOKEN_STOPWORDS}


def _values_overlap(left: str, right: str) -> bool:
    left_text = _canonical(left)
    right_text = _canonical(right)
    if not left_text or not right_text:
        return False
    if left_text in right_text or right_text in left_text:
        return True
    left_tokens = _tokens(left)
    right_tokens = _tokens(right)
    if not left_tokens or not right_tokens:
        return False
    return bool(left_tokens & right_tokens)


def _is_more_specific(candidate_value: str, existing_value: str) -> bool:
    candidate_text = _canonical(candidate_value)
    existing_text = _canonical(existing_value)
    if not candidate_text or not existing_text or candidate_text == existing_text:
        return False
    if existing_text in candidate_text and len(candidate_text) > len(existing_text):
        return True
    candidate_tokens = _tokens(candidate_value)
    existing_tokens = _tokens(existing_value)
    return bool(existing_tokens) and existing_tokens < candidate_tokens


def _opposite_polarity(left: str, right: str) -> bool:
    return (
        left in POSITIVE_POLARITIES
        and right in NEGATIVE_POLARITIES
        or left in NEGATIVE_POLARITIES
        and right in POSITIVE_POLARITIES
    )


def _same_polarity_family(left: str, right: str) -> bool:
    return (
        left == right
        or left in POSITIVE_POLARITIES
        and right in POSITIVE_POLARITIES
        or left in NEGATIVE_POLARITIES
        and right in NEGATIVE_POLARITIES
    )
