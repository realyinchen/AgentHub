from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from app.infra.database import get_database
from app.services.memory.admission import MemoryAdmissionEngine
from app.services.memory.conflicts import MemoryConflictResolver
from app.services.memory.contracts import MemoryCandidate, MemoryEvent
from app.services.memory.providers.postgres import PostgresMemoryProvider
from app.services.memory.write_contracts import (
    MemoryCommitCommand,
    MemoryWriteOutcome,
    ResolvedMemoryFact,
)


@dataclass(frozen=True)
class _PreparedCommit:
    candidate: MemoryCandidate
    decision: str
    target: MemoryEvent | None
    conflict: dict[str, Any]


class MemoryCommitter:
    """The sole v2 component that may create or revise durable memory."""

    def __init__(self) -> None:
        self._admission = MemoryAdmissionEngine()
        self._conflicts = MemoryConflictResolver()

    async def commit(
        self,
        command: MemoryCommitCommand,
        *,
        user_id: UUID,
        thread_id: UUID | None,
    ) -> MemoryWriteOutcome:
        conflicting_batch_key = _conflicting_batch_key(command.facts)
        if conflicting_batch_key:
            return MemoryWriteOutcome(
                status="clarification_required",
                clarification_question=(
                    f"你同时给出了多个不同的“{conflicting_batch_key}”值，"
                    "请直接重新陈述最终希望我记住的完整事实。"
                ),
                reason_codes=["batch_canonical_key_conflict"],
            )

        candidates = [
            _candidate_from_fact(
                fact,
                user_id=user_id,
                thread_id=thread_id,
            )
            for fact in _dedupe_facts(command.facts)
        ]
        db = get_database()
        async with db.session() as session:
            provider = PostgresMemoryProvider(session)
            current_result = await provider.list_current(
                user_id=user_id,
                query="",
                memory_types=None,
                limit=100,
            )
            current = list(current_result.memories)
            prepared: list[_PreparedCommit] = []
            admission_rows: list[dict[str, Any]] = []

            for candidate in candidates:
                admission = self._admission.admit(candidate)
                admission_rows.append(admission.model_dump(mode="json"))
                if admission.decision != "allow":
                    status = (
                        "clarification_required"
                        if admission.decision == "needs_confirmation"
                        else "rejected"
                    )
                    return MemoryWriteOutcome(
                        status=status,
                        clarification_question=(
                            "这条信息还不满足长期记忆的写入条件，请补充更明确的事实。"
                            if status == "clarification_required"
                            else ""
                        ),
                        reason_codes=[admission.reason or admission.decision],
                        admission=admission_rows,
                    )

                resolution = self._conflicts.resolve(candidate, current)
                target = _memory_by_id(current, resolution.target_memory_id)
                if resolution.decision == "needs_confirmation":
                    return MemoryWriteOutcome(
                        status="clarification_required",
                        clarification_question=_conflict_question(
                            candidate,
                            target,
                        ),
                        reason_codes=[resolution.reason],
                        admission=admission_rows,
                    )
                if resolution.decision == "revise_existing" and target is None:
                    return MemoryWriteOutcome(
                        status="clarification_required",
                        clarification_question=(
                            "检测到记忆冲突，但无法确定应替换哪条记录。"
                            "请直接重新陈述最终希望保留的完整事实。"
                        ),
                        reason_codes=["conflict_target_missing"],
                        admission=admission_rows,
                    )
                prepared.append(
                    _PreparedCommit(
                        candidate=candidate,
                        decision=resolution.decision,
                        target=target,
                        conflict=resolution.model_dump(mode="json"),
                    )
                )

            saved: list[MemoryEvent] = []
            for item in prepared:
                if item.decision == "skip_duplicate":
                    if item.target is not None:
                        saved.append(item.target)
                    continue
                event = _event_with_resolution(item.candidate, item.conflict)
                if item.decision == "revise_existing" and item.target is not None:
                    memory = await provider.revise(
                        user_id=user_id,
                        new_event=event,
                        memory_id=item.target.id,
                        old_value=item.target.value,
                        old_subject=item.target.subject,
                        old_type=item.target.type,
                    )
                else:
                    memory = await provider.remember(event)
                saved.append(memory)

        all_duplicates = bool(prepared) and all(
            item.decision == "skip_duplicate" for item in prepared
        )
        return MemoryWriteOutcome(
            status="noop_duplicate" if all_duplicates else "committed",
            facts=command.facts,
            memories=[memory.model_dump(mode="json") for memory in saved],
            reason_codes=(
                ["all_facts_already_committed"]
                if all_duplicates
                else ["precommit_pipeline_completed"]
            ),
            admission=admission_rows,
        )


def _candidate_from_fact(
    fact: ResolvedMemoryFact,
    *,
    user_id: UUID,
    thread_id: UUID | None,
) -> MemoryCandidate:
    profile_key = (
        fact.state_key.removeprefix("profile.")
        if fact.state_key.startswith("profile.")
        else ""
    )
    metadata: dict[str, Any] = {
        "capture_source": "precommit_memory_pipeline_v2",
        "precommit": {
            "source_identified": True,
            "reference_resolved": True,
            "completeness_validated": True,
            "persistence_approved": True,
            "extraction_method": fact.extraction_method,
            "source_kind": fact.source.source_kind,
            "source_turn_offset": fact.source.turn_offset,
        },
        "user_state": {
            "status": "active",
            "category": fact.category,
            "state_key": fact.state_key,
            "summary": fact.summary,
            "raw_text": fact.source.excerpt,
            "state_value": fact.state_value,
            "relation": fact.relation,
            "use_when": fact.use_when,
            "valid_until": None,
            "confirmation_question": "",
            "organizer": "precommit_memory_pipeline_v2",
        },
        "index_projection": {
            "status": "required",
            "canonical_fact_version": 1,
        },
    }
    if profile_key:
        metadata["profile_key"] = profile_key
    return MemoryCandidate(
        type=fact.legacy_type,
        subject=fact.legacy_subject,
        value=fact.legacy_value,
        polarity=fact.polarity,
        scope="long_term_memory",
        source_text=fact.source.excerpt,
        source_kind="user_message",
        confidence=fact.extraction_confidence,
        user_id=user_id,
        thread_id=thread_id,
        metadata=metadata,
    )


def _event_with_resolution(
    candidate: MemoryCandidate,
    conflict: dict[str, Any],
) -> MemoryEvent:
    metadata = dict(candidate.metadata)
    metadata["conflict_resolution"] = conflict
    precommit = dict(metadata.get("precommit") or {})
    precommit["conflict_checked"] = True
    metadata["precommit"] = precommit
    return candidate.model_copy(update={"metadata": metadata}).to_memory_event()


def _memory_by_id(
    memories: list[MemoryEvent],
    memory_id: UUID | None,
) -> MemoryEvent | None:
    if memory_id is None:
        return None
    return next((memory for memory in memories if memory.id == memory_id), None)


def _conflict_question(
    candidate: MemoryCandidate,
    target: MemoryEvent | None,
) -> str:
    if target is None:
        return (
            f"“{candidate.value}”可能与已有信息冲突。"
            "请直接重新陈述最终希望我记住的完整事实。"
        )
    return (
        f"已有记录是“{target.value}”，新信息是“{candidate.value}”。"
        "请直接重新陈述最终希望保留的完整事实。"
    )


def _dedupe_facts(
    facts: list[ResolvedMemoryFact],
) -> list[ResolvedMemoryFact]:
    result: list[ResolvedMemoryFact] = []
    seen: set[tuple[str, str]] = set()
    for fact in facts:
        key = (fact.state_key, repr(sorted(fact.state_value.items())))
        if key in seen:
            continue
        seen.add(key)
        result.append(fact)
    return result


def _conflicting_batch_key(
    facts: list[ResolvedMemoryFact],
) -> str:
    by_key: dict[str, set[str]] = {}
    for fact in facts:
        by_key.setdefault(fact.state_key, set()).add(
            repr(sorted(fact.state_value.items()))
        )
    return next((key for key, values in by_key.items() if len(values) > 1), "")
