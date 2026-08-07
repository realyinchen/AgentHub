from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.conversation_event import ConversationEventRecord
from app.models.memory import MemoryEventRecord
from app.services.memory.version_contracts import (
    CanonicalMemoryFact,
    MemoryMutation,
    MemoryMutationReceipt,
    MemoryVersionCommitCommand,
    MemoryVersionForgetCommand,
    MemoryVersionRecord,
)
from app.services.memory.version_errors import (
    MemoryVersionIdempotencyConflict,
    MemoryVersionSourceError,
    MemoryVersionTargetNotFound,
)


class MemoryVersionStore:
    """Commit canonical facts into linear chains; never interpret proposals."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def commit(
        self,
        command: MemoryVersionCommitCommand,
        *,
        user_id: UUID,
        thread_id: UUID | None,
    ) -> MemoryMutationReceipt:
        source = await self._require_user_source(
            source_event_id=command.source_event_id,
            user_id=user_id,
            thread_id=thread_id,
        )
        _assert_unique_batch(command.facts)
        for fact in command.facts:
            if fact.evidence_quote.casefold() not in source.content.casefold():
                raise MemoryVersionSourceError(
                    "canonical evidence is absent from the source user event"
                )

        facts = sorted(command.facts, key=lambda item: item.memory_key)
        await self._lock_memory_keys(
            user_id=user_id,
            memory_keys=[item.memory_key for item in facts],
        )
        await self._assert_receipt_reuse_is_compatible(
            user_id=user_id,
            receipt_id=command.receipt_id,
            facts=facts,
        )
        heads = {
            fact.memory_key: await self._current_head(
                user_id=user_id,
                memory_key=fact.memory_key,
                for_update=True,
            )
            for fact in facts
        }

        prepared: list[
            tuple[CanonicalMemoryFact, MemoryEventRecord | None, str]
        ] = []
        for fact in facts:
            head = heads[fact.memory_key]
            if (
                head is not None
                and head.operation != "forget"
                and head.canonical_hash == fact.canonical_hash
            ):
                prepared.append((fact, head, "noop_duplicate"))
            elif head is None:
                prepared.append((fact, None, "created"))
            else:
                prepared.append((fact, head, "revised"))

        mutations: list[MemoryMutation] = []
        for fact, previous, status in prepared:
            if status == "noop_duplicate":
                if previous is None:
                    raise RuntimeError("duplicate preflight lost its chain head")
                mutations.append(
                    MemoryMutation(
                        memory_key=fact.memory_key,
                        status="noop_duplicate",
                        version=_record_to_version(previous),
                    )
                )
                continue
            record = await self._insert_fact_version(
                fact,
                previous=previous,
                user_id=user_id,
                thread_id=thread_id,
                source_event_id=command.source_event_id,
                receipt_id=command.receipt_id,
                operation=("create" if previous is None else "correct"),
                mutation_status=status,
            )
            mutations.append(
                MemoryMutation(
                    memory_key=fact.memory_key,
                    status=status,
                    version=_record_to_version(record),
                    previous=(
                        _record_to_version(previous)
                        if previous is not None
                        else None
                    ),
                )
            )

        all_noop = bool(mutations) and all(
            item.status == "noop_duplicate" for item in mutations
        )
        return MemoryMutationReceipt(
            receipt_id=command.receipt_id,
            status="noop_duplicate" if all_noop else "committed",
            mutations=mutations,
        )

    async def forget(
        self,
        command: MemoryVersionForgetCommand,
        *,
        user_id: UUID,
        thread_id: UUID | None,
    ) -> MemoryMutationReceipt:
        source = await self._require_user_source(
            source_event_id=command.source_event_id,
            user_id=user_id,
            thread_id=thread_id,
        )
        if command.evidence_quote.casefold() not in source.content.casefold():
            raise MemoryVersionSourceError(
                "forget evidence is absent from the source user event"
            )
        keys = sorted(set(command.memory_keys))
        await self._lock_memory_keys(user_id=user_id, memory_keys=keys)
        await self._assert_forget_receipt_reuse_is_compatible(
            user_id=user_id,
            receipt_id=command.receipt_id,
            memory_keys=keys,
        )
        heads = {
            key: await self._current_head(
                user_id=user_id,
                memory_key=key,
                for_update=True,
            )
            for key in keys
        }
        missing = [key for key, head in heads.items() if head is None]
        if missing:
            raise MemoryVersionTargetNotFound(
                "memory targets do not exist: " + ", ".join(missing)
            )

        mutations: list[MemoryMutation] = []
        for memory_key in keys:
            previous = heads[memory_key]
            if previous is None:
                raise RuntimeError("forget preflight lost its chain head")
            if previous.operation == "forget":
                mutations.append(
                    MemoryMutation(
                        memory_key=memory_key,
                        status="noop_duplicate",
                        version=_record_to_version(previous),
                    )
                )
                continue
            record = await self._insert_tombstone(
                previous,
                evidence_quote=command.evidence_quote,
                source_event_id=command.source_event_id,
                receipt_id=command.receipt_id,
                user_id=user_id,
                thread_id=thread_id,
            )
            mutations.append(
                MemoryMutation(
                    memory_key=memory_key,
                    status="forgotten",
                    version=_record_to_version(record),
                )
            )

        all_noop = all(
            item.status == "noop_duplicate" for item in mutations
        )
        return MemoryMutationReceipt(
            receipt_id=command.receipt_id,
            status="noop_duplicate" if all_noop else "committed",
            mutations=mutations,
        )

    async def list_current(
        self,
        *,
        user_id: UUID,
        schema_key: str | None = None,
        limit: int = 100,
    ) -> list[MemoryVersionRecord]:
        stmt = select(MemoryEventRecord).where(
            MemoryEventRecord.user_id == user_id,
            MemoryEventRecord.memory_key.is_not(None),
            MemoryEventRecord.superseded_by.is_(None),
            MemoryEventRecord.is_deleted.is_(False),
            MemoryEventRecord.operation != "forget",
        )
        if schema_key:
            stmt = stmt.where(MemoryEventRecord.schema_key == schema_key)
        result = await self._session.execute(
            stmt.order_by(MemoryEventRecord.valid_from.desc()).limit(
                max(1, min(int(limit), 500))
            )
        )
        return [_record_to_version(item) for item in result.scalars().all()]

    async def list_history(
        self,
        *,
        user_id: UUID,
        schema_key: str | None = None,
        limit: int = 500,
    ) -> list[MemoryVersionRecord]:
        """Read every version in every chain, including tombstones.

        History reads are bounded; scopes such as previous/earliest/timeline
        select from this full material rather than a second execution channel.
        """

        stmt = select(MemoryEventRecord).where(
            MemoryEventRecord.user_id == user_id,
            MemoryEventRecord.memory_key.is_not(None),
        )
        if schema_key:
            stmt = stmt.where(MemoryEventRecord.schema_key == schema_key)
        result = await self._session.execute(
            stmt.order_by(
                MemoryEventRecord.memory_key.asc(),
                MemoryEventRecord.version_no.asc(),
            ).limit(max(1, min(int(limit), 1000)))
        )
        return [_record_to_version(item) for item in result.scalars().all()]

    async def history(
        self,
        *,
        user_id: UUID,
        memory_key: str,
    ) -> list[MemoryVersionRecord]:
        result = await self._session.execute(
            select(MemoryEventRecord)
            .where(
                MemoryEventRecord.user_id == user_id,
                MemoryEventRecord.memory_key == memory_key,
            )
            .order_by(MemoryEventRecord.version_no.asc())
        )
        return [_record_to_version(item) for item in result.scalars().all()]

    async def _insert_fact_version(
        self,
        fact: CanonicalMemoryFact,
        *,
        previous: MemoryEventRecord | None,
        user_id: UUID,
        thread_id: UUID | None,
        source_event_id: UUID,
        receipt_id: str,
        operation: str,
        mutation_status: str,
    ) -> MemoryEventRecord:
        now = datetime.now(timezone.utc)
        record_id = uuid.uuid4()
        record = MemoryEventRecord(
            id=record_id,
            user_id=user_id,
            thread_id=thread_id,
            type=_legacy_type(fact.schema_key),
            subject=_legacy_subject(fact.schema_key),
            value=_stable_json(fact.value),
            polarity=_legacy_polarity(fact),
            confidence=1.0,
            source="chat_turn",
            metadata_json={
                "memory_v2": {
                    "subject": fact.subject,
                    "predicate": fact.predicate,
                    "value": fact.value,
                    "qualifiers": fact.qualifiers,
                    "evidence_quote": fact.evidence_quote,
                    "mutation_status": mutation_status,
                },
                "precommit": {
                    "source_identified": True,
                    "reference_resolved": True,
                    "completeness_validated": True,
                    "persistence_approved": True,
                    "conflict_checked": True,
                },
            },
            revision_of=(previous.id if previous is not None else None),
            chain_id=(
                previous.chain_id
                if previous is not None
                else uuid.uuid4()
            ),
            schema_key=fact.schema_key,
            memory_key=fact.memory_key,
            version_no=(
                int(previous.version_no or 0) + 1
                if previous is not None
                else 1
            ),
            operation=operation,
            previous_version_id=(
                previous.id if previous is not None else None
            ),
            source_event_id=source_event_id,
            receipt_id=receipt_id,
            canonical_hash=fact.canonical_hash,
            schema_version=fact.schema_version,
            valid_from=now,
            superseded_by=(record_id if previous is not None else None),
        )
        self._session.add(record)
        await self._session.flush()
        if previous is not None:
            previous.superseded_by = record.id
            previous.valid_to = now
            previous.updated_at = now
            await self._session.flush()
            record.superseded_by = None
            await self._session.flush()
        await self._session.refresh(record)
        return record

    async def _insert_tombstone(
        self,
        previous: MemoryEventRecord,
        *,
        evidence_quote: str,
        source_event_id: UUID,
        receipt_id: str,
        user_id: UUID,
        thread_id: UUID | None,
    ) -> MemoryEventRecord:
        now = datetime.now(timezone.utc)
        record_id = uuid.uuid4()
        canonical_hash = hashlib.sha256(
            f"forget:{previous.id}:{source_event_id}".encode("utf-8")
        ).hexdigest()
        record = MemoryEventRecord(
            id=record_id,
            user_id=user_id,
            thread_id=thread_id,
            type="forget",
            subject=previous.subject,
            value=evidence_quote,
            polarity="neutral",
            confidence=1.0,
            source="chat_turn",
            metadata_json={
                "memory_v2": {
                    "subject": _memory_v2(previous).get("subject", "self"),
                    "predicate": previous.schema_key,
                    "value": {},
                    "qualifiers": {},
                    "evidence_quote": evidence_quote,
                    "mutation_status": "forgotten",
                }
            },
            revision_of=previous.id,
            chain_id=previous.chain_id,
            schema_key=previous.schema_key,
            memory_key=previous.memory_key,
            version_no=int(previous.version_no or 0) + 1,
            operation="forget",
            previous_version_id=previous.id,
            source_event_id=source_event_id,
            receipt_id=receipt_id,
            canonical_hash=canonical_hash,
            schema_version=previous.schema_version,
            valid_from=now,
            is_deleted=True,
            deleted_at=now,
            superseded_by=record_id,
        )
        self._session.add(record)
        await self._session.flush()
        previous.superseded_by = record.id
        previous.valid_to = now
        previous.updated_at = now
        await self._session.flush()
        record.superseded_by = None
        await self._session.flush()
        await self._session.refresh(record)
        return record

    async def _require_user_source(
        self,
        *,
        source_event_id: UUID,
        user_id: UUID,
        thread_id: UUID | None,
    ) -> ConversationEventRecord:
        stmt = select(ConversationEventRecord).where(
            ConversationEventRecord.id == source_event_id,
            ConversationEventRecord.user_id == user_id,
            ConversationEventRecord.role == "user",
        )
        if thread_id is not None:
            stmt = stmt.where(
                ConversationEventRecord.thread_id == thread_id
            )
        result = await self._session.execute(stmt)
        source = result.scalar_one_or_none()
        if source is None:
            raise MemoryVersionSourceError(
                "memory commits require an owned user conversation event"
            )
        return source

    async def _lock_memory_keys(
        self,
        *,
        user_id: UUID,
        memory_keys: list[str],
    ) -> None:
        for memory_key in sorted(set(memory_keys)):
            await self._session.execute(
                text(
                    "SELECT pg_advisory_xact_lock("
                    "hashtextextended(:lock_key, 0))"
                ),
                {"lock_key": f"{user_id}:{memory_key}"},
            )

    async def _current_head(
        self,
        *,
        user_id: UUID,
        memory_key: str,
        for_update: bool,
    ) -> MemoryEventRecord | None:
        stmt = select(MemoryEventRecord).where(
            MemoryEventRecord.user_id == user_id,
            MemoryEventRecord.memory_key == memory_key,
            MemoryEventRecord.superseded_by.is_(None),
        )
        if for_update:
            stmt = stmt.with_for_update()
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def _assert_receipt_reuse_is_compatible(
        self,
        *,
        user_id: UUID,
        receipt_id: str,
        facts: list[CanonicalMemoryFact],
    ) -> None:
        result = await self._session.execute(
            select(MemoryEventRecord).where(
                MemoryEventRecord.user_id == user_id,
                MemoryEventRecord.receipt_id == receipt_id,
            )
        )
        existing = list(result.scalars().all())
        if not existing:
            return
        expected = {
            item.memory_key: item.canonical_hash for item in facts
        }
        actual = {
            str(item.memory_key): str(item.canonical_hash)
            for item in existing
        }
        if any(
            key not in expected or expected[key] != canonical_hash
            for key, canonical_hash in actual.items()
        ):
            raise MemoryVersionIdempotencyConflict(
                "receipt_id was already used for different canonical facts"
            )

    async def _assert_forget_receipt_reuse_is_compatible(
        self,
        *,
        user_id: UUID,
        receipt_id: str,
        memory_keys: list[str],
    ) -> None:
        result = await self._session.execute(
            select(MemoryEventRecord).where(
                MemoryEventRecord.user_id == user_id,
                MemoryEventRecord.receipt_id == receipt_id,
            )
        )
        existing = list(result.scalars().all())
        if not existing:
            return
        actual_keys = {str(item.memory_key) for item in existing}
        if (
            actual_keys != set(memory_keys)
            or any(item.operation != "forget" for item in existing)
        ):
            raise MemoryVersionIdempotencyConflict(
                "receipt_id was already used for another memory mutation"
            )


def _assert_unique_batch(facts: list[CanonicalMemoryFact]) -> None:
    by_key: dict[str, set[str]] = {}
    for fact in facts:
        by_key.setdefault(fact.memory_key, set()).add(
            fact.canonical_hash
        )
    conflicts = [
        key for key, hashes in by_key.items() if len(hashes) > 1
    ]
    if conflicts:
        raise ValueError(
            "one commit batch contains conflicting memory keys: "
            + ", ".join(conflicts)
        )


def _record_to_version(record: MemoryEventRecord) -> MemoryVersionRecord:
    memory_v2 = _memory_v2(record)
    if (
        record.chain_id is None
        or record.schema_key is None
        or record.memory_key is None
        or record.version_no is None
        or record.operation is None
        or record.source_event_id is None
        or record.receipt_id is None
        or record.canonical_hash is None
        or record.schema_version is None
        or record.valid_from is None
    ):
        raise ValueError("legacy memory row is not a versioned memory record")
    return MemoryVersionRecord(
        id=record.id,
        user_id=record.user_id,
        thread_id=record.thread_id,
        chain_id=record.chain_id,
        schema_key=record.schema_key,
        memory_key=record.memory_key,
        version_no=record.version_no,
        operation=record.operation,
        previous_version_id=record.previous_version_id,
        superseded_by=record.superseded_by,
        source_event_id=record.source_event_id,
        receipt_id=record.receipt_id,
        canonical_hash=record.canonical_hash,
        schema_version=record.schema_version,
        subject=str(memory_v2.get("subject") or "self"),
        predicate=str(memory_v2.get("predicate") or record.schema_key),
        value=(
            dict(memory_v2.get("value") or {})
            if isinstance(memory_v2.get("value"), dict)
            else {}
        ),
        qualifiers=(
            dict(memory_v2.get("qualifiers") or {})
            if isinstance(memory_v2.get("qualifiers"), dict)
            else {}
        ),
        evidence_quote=str(memory_v2.get("evidence_quote") or ""),
        is_tombstone=record.operation == "forget" or record.is_deleted,
        valid_from=record.valid_from,
        valid_to=record.valid_to,
    )


def _memory_v2(record: MemoryEventRecord) -> dict[str, Any]:
    metadata = record.metadata_json or {}
    value = metadata.get("memory_v2")
    return value if isinstance(value, dict) else {}


def _legacy_type(schema_key: str) -> str:
    if schema_key.startswith("preference."):
        return "preference"
    if schema_key.startswith("relationship."):
        return "entity"
    if schema_key.startswith("feedback."):
        return "feedback"
    return "state"


def _legacy_subject(schema_key: str) -> str:
    return "entity" if schema_key.startswith("relationship.") else "user"


def _legacy_polarity(fact: CanonicalMemoryFact) -> str:
    value = str(fact.value.get("polarity") or "neutral").lower()
    return (
        value
        if value in {"like", "dislike", "avoid", "want", "neutral"}
        else "neutral"
    )


def _stable_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
