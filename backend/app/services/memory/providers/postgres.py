from __future__ import annotations

import re
from typing import Any
from uuid import UUID

from sqlalchemy import String, cast, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.crud.book import get_or_create_preference_profile
from app.models.base import utc_now
from app.models.book import BookInteraction
from app.models.memory import MemoryEventRecord
from app.services.memory.contracts import (
    CurrentMemoryListResult,
    MEMORY_TYPES,
    MemoryEvent,
    MemoryEventListResult,
    MemoryForgetResult,
    MemorySearchResult,
    normalize_memory_token,
    validate_optional_memory_token,
)
from app.services.memory.providers.base import MemoryProvider


_PROFILE_TYPES = {"preference", "correction"}
_LIKE_POLARITIES = {"like", "want"}
_DISLIKE_POLARITIES = {"dislike", "avoid"}
_READING_TYPES = {"feedback", "reading_state"}
_READING_POLARITIES = {"want", "read"}
_TAG_SUBJECTS = {"tag", "theme", "style", "genre", "mood", "pacing", "content"}
_AUTHOR_SUBJECTS = {"author"}
_QUERY_STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "but",
    "for",
    "fine",
    "is",
    "just",
    "not",
    "or",
    "the",
    "too",
    "with",
}


def _clean_list(values: list[str] | None) -> list[str]:
    seen: set[str] = set()
    cleaned: list[str] = []
    for value in values or []:
        item = str(value).strip()
        key = item.lower()
        if item and key not in seen:
            seen.add(key)
            cleaned.append(item)
    return cleaned


def _add_unique(values: list[str] | None, value: str) -> list[str]:
    return _clean_list([*(values or []), value])


def _remove_value(values: list[str] | None, value: str) -> list[str]:
    key = value.strip().lower()
    return [item for item in _clean_list(values) if item.lower() != key]


def _merge_metadata(existing: dict[str, Any] | None, incoming: dict[str, Any]) -> dict:
    merged = dict(existing or {})
    merged.update(incoming)
    merged["touch_count"] = int(merged.get("touch_count") or 0) + 1
    return merged


def _normalize_memory_types(memory_types: list[str] | None) -> list[str]:
    normalized: list[str] = []
    for item in memory_types or []:
        token = validate_optional_memory_token("memory_type", item, MEMORY_TYPES)
        if token and token not in normalized:
            normalized.append(token)
    return normalized


def _query_terms(query: str, max_terms: int = 8) -> list[str]:
    raw_terms = re.findall(r"[\w\u4e00-\u9fff]+", query.lower())
    terms: list[str] = []
    seen: set[str] = set()
    for term in raw_terms:
        if len(term) < 2 or term in _QUERY_STOPWORDS or term in seen:
            continue
        seen.add(term)
        terms.append(term)
        if len(terms) >= max_terms:
            break
    return terms


class PostgresMemoryProvider(MemoryProvider):
    """Postgres implementation of the app-owned memory contract."""

    provider_name = "postgres"

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def search(
        self,
        *,
        user_id: UUID,
        query: str = "",
        thread_id: UUID | None = None,
        memory_types: list[str] | None = None,
        limit: int = 10,
    ) -> MemorySearchResult:
        profile = await get_or_create_preference_profile(self.session, user_id)
        events = await self._search_events(
            user_id=user_id,
            query=query,
            thread_id=thread_id,
            memory_types=memory_types,
            limit=limit,
        )
        interactions = await self._search_book_interactions(
            user_id=user_id,
            query=query,
            limit=limit,
        )

        return MemorySearchResult(
            profile_summary=profile.profile_summary,
            preferred_tags=profile.preferred_tags,
            disliked_tags=profile.disliked_tags,
            favorite_authors=profile.favorite_authors,
            disliked_authors=profile.disliked_authors,
            reading_states=self._build_reading_states(events, interactions),
            relevant_events=[self._event_from_record(event) for event in events],
            provider_sources=[self.provider_name],
        )

    async def list_events(
        self,
        *,
        user_id: UUID,
        query: str = "",
        memory_types: list[str] | None = None,
        include_forgotten: bool = False,
        include_superseded: bool = False,
        include_audit: bool = False,
        limit: int = 50,
        offset: int = 0,
    ) -> MemoryEventListResult:
        stmt = select(MemoryEventRecord).where(MemoryEventRecord.user_id == user_id)
        if not include_forgotten:
            stmt = stmt.where(MemoryEventRecord.is_deleted.is_(False))
        if not include_superseded:
            stmt = stmt.where(MemoryEventRecord.superseded_by.is_(None))
        if not include_audit:
            stmt = stmt.where(MemoryEventRecord.type != "forget")

        normalized_types = _normalize_memory_types(memory_types)
        if normalized_types:
            stmt = stmt.where(MemoryEventRecord.type.in_(normalized_types))
        if query.strip():
            stmt = stmt.where(self._memory_text_filter(query))

        count_stmt = select(func.count()).select_from(stmt.order_by(None).subquery())
        total = int(await self.session.scalar(count_stmt) or 0)
        page_limit = max(1, min(limit, 100))
        page_offset = max(0, offset)
        result = await self.session.execute(
            stmt.order_by(
                MemoryEventRecord.updated_at.desc(),
                MemoryEventRecord.created_at.desc(),
            )
            .offset(page_offset)
            .limit(page_limit)
        )

        return MemoryEventListResult(
            user_id=user_id,
            events=[self._event_from_record(event) for event in result.scalars().all()],
            total=total,
            limit=page_limit,
            offset=page_offset,
            include_forgotten=include_forgotten,
            include_superseded=include_superseded,
            include_audit=include_audit,
            provider_sources=[self.provider_name],
        )

    async def list_current(
        self,
        *,
        user_id: UUID,
        query: str = "",
        memory_types: list[str] | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> CurrentMemoryListResult:
        stmt = self._active_events_stmt(user_id)

        normalized_types = _normalize_memory_types(memory_types)
        if normalized_types:
            stmt = stmt.where(MemoryEventRecord.type.in_(normalized_types))
        if query.strip():
            stmt = stmt.where(self._memory_text_filter(query))

        count_stmt = select(func.count()).select_from(stmt.order_by(None).subquery())
        total = int(await self.session.scalar(count_stmt) or 0)
        page_limit = max(1, min(limit, 100))
        page_offset = max(0, offset)
        result = await self.session.execute(
            stmt.order_by(
                MemoryEventRecord.updated_at.desc(),
                MemoryEventRecord.created_at.desc(),
            )
            .offset(page_offset)
            .limit(page_limit)
        )

        return CurrentMemoryListResult(
            user_id=user_id,
            memories=[self._event_from_record(event) for event in result.scalars().all()],
            total=total,
            limit=page_limit,
            offset=page_offset,
            provider_sources=[self.provider_name],
        )

    async def remember(self, event: MemoryEvent) -> MemoryEvent:
        normalized = self._normalize_event(event)
        await get_or_create_preference_profile(self.session, normalized.user_id)
        duplicate = await self._find_duplicate(normalized)
        if duplicate is not None:
            duplicate.confidence = max(duplicate.confidence, normalized.confidence)
            duplicate.thread_id = normalized.thread_id or duplicate.thread_id
            duplicate.source = normalized.source
            duplicate.metadata_json = _merge_metadata(
                duplicate.metadata_json, normalized.metadata
            )
            duplicate.updated_at = utc_now()
            await self.session.flush()
            await self.session.refresh(duplicate)
            await self._apply_event_to_profile(duplicate)
            return self._event_from_record(duplicate)

        record = self._record_from_event(normalized)
        self.session.add(record)
        await self.session.flush()
        await self.session.refresh(record)
        await self._supersede_conflicts(record)
        await self._apply_event_to_profile(record)
        await self.session.flush()
        await self.session.refresh(record)
        return self._event_from_record(record)

    async def revise(
        self,
        *,
        user_id: UUID,
        new_event: MemoryEvent,
        memory_id: UUID | None = None,
        old_value: str = "",
        old_subject: str = "",
        old_type: str = "",
    ) -> MemoryEvent:
        target = await self._find_revision_target(
            user_id=user_id,
            memory_id=memory_id,
            old_value=old_value,
            old_subject=old_subject,
            old_type=old_type,
        )
        await get_or_create_preference_profile(self.session, user_id)
        metadata = dict(new_event.metadata)
        if target is None:
            metadata["revision_target_found"] = False
        normalized = self._normalize_event(
            new_event.model_copy(
                update={
                    "user_id": user_id,
                    "type": new_event.type or "correction",
                    "revision_of": target.id if target else None,
                    "metadata": metadata,
                }
            )
        )
        record = self._record_from_event(normalized)
        self.session.add(record)
        await self.session.flush()
        await self.session.refresh(record)

        if target is not None:
            target.superseded_by = record.id
            target.updated_at = utc_now()
            await self._remove_event_from_profile(target)

        await self._supersede_conflicts(record)
        await self._apply_event_to_profile(record)
        await self.session.flush()
        await self.session.refresh(record)
        return self._event_from_record(record)

    async def forget(
        self,
        *,
        user_id: UUID,
        memory_id: UUID | None = None,
        subject: str = "",
        value: str = "",
        memory_type: str = "",
        thread_id: UUID | None = None,
        reason: str = "",
    ) -> MemoryForgetResult:
        targets = await self._find_forget_targets(
            user_id=user_id,
            memory_id=memory_id,
            subject=subject,
            value=value,
            memory_type=memory_type,
            thread_id=thread_id,
        )
        now = utc_now()
        forgotten_ids: list[UUID] = []
        for target in targets:
            target.is_deleted = True
            target.deleted_at = now
            target.updated_at = now
            forgotten_ids.append(target.id)
            await self._remove_event_from_profile(target)
            await self._mark_related_book_interaction_forgotten(target)

        audit_value = reason.strip() or "forget memory"
        audit = MemoryEventRecord(
            user_id=user_id,
            thread_id=thread_id,
            type="forget",
            subject=normalize_memory_token(subject) or "user",
            value=audit_value,
            polarity="neutral",
            confidence=1.0,
            source="chat_turn",
            metadata_json={"forgotten_event_ids": [str(item) for item in forgotten_ids]},
        )
        self.session.add(audit)
        await self.session.flush()

        return MemoryForgetResult(
            user_id=user_id,
            forgotten_count=len(forgotten_ids),
            forgotten_event_ids=forgotten_ids,
            provider_sources=[self.provider_name],
        )

    async def _search_events(
        self,
        *,
        user_id: UUID,
        query: str,
        thread_id: UUID | None,
        memory_types: list[str] | None,
        limit: int,
    ) -> list[MemoryEventRecord]:
        stmt = self._active_events_stmt(user_id).order_by(
            MemoryEventRecord.confidence.desc(),
            MemoryEventRecord.updated_at.desc(),
        )
        if memory_types:
            stmt = stmt.where(
                MemoryEventRecord.type.in_(_normalize_memory_types(memory_types))
            )
        if query.strip():
            stmt = stmt.where(self._memory_text_filter(query))
        result = await self.session.execute(stmt.limit(max(1, min(limit, 50))))
        return list(result.scalars().all())

    async def _search_book_interactions(
        self,
        *,
        user_id: UUID,
        query: str,
        limit: int,
    ) -> list[BookInteraction]:
        stmt = (
            select(BookInteraction)
            .where(BookInteraction.user_id == user_id)
            .order_by(BookInteraction.created_at.desc())
            .limit(max(1, min(limit, 50)))
        )
        if query.strip():
            predicates = []
            for term in _query_terms(query):
                pattern = f"%{term}%"
                predicates.extend(
                    [
                        BookInteraction.book_title.ilike(pattern),
                        BookInteraction.note.ilike(pattern),
                        BookInteraction.interaction_type.ilike(pattern),
                    ]
                )
            if not predicates:
                pattern = f"%{query.strip()}%"
                predicates = [
                    BookInteraction.book_title.ilike(pattern),
                    BookInteraction.note.ilike(pattern),
                    BookInteraction.interaction_type.ilike(pattern),
                ]
            stmt = stmt.where(or_(*predicates))
        result = await self.session.execute(stmt)
        interactions = []
        for interaction in result.scalars().all():
            if (interaction.raw_data or {}).get("memory_forgotten") is True:
                continue
            interactions.append(interaction)
        return interactions[: max(1, min(limit, 50))]

    def _active_events_stmt(self, user_id: UUID):
        return select(MemoryEventRecord).where(
            MemoryEventRecord.user_id == user_id,
            MemoryEventRecord.is_deleted.is_(False),
            MemoryEventRecord.superseded_by.is_(None),
            MemoryEventRecord.type != "forget",
        )

    async def _find_duplicate(
        self, event: MemoryEvent
    ) -> MemoryEventRecord | None:
        result = await self.session.execute(
            self._active_events_stmt(event.user_id)
            .where(
                MemoryEventRecord.type == event.type,
                MemoryEventRecord.subject == event.subject,
                func.lower(MemoryEventRecord.value) == event.value.lower(),
                MemoryEventRecord.polarity == event.polarity,
            )
            .order_by(MemoryEventRecord.updated_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def _find_revision_target(
        self,
        *,
        user_id: UUID,
        memory_id: UUID | None,
        old_value: str,
        old_subject: str,
        old_type: str,
    ) -> MemoryEventRecord | None:
        stmt = self._active_events_stmt(user_id)
        if memory_id is not None:
            stmt = stmt.where(MemoryEventRecord.id == memory_id)
        else:
            if old_value.strip():
                stmt = stmt.where(
                    func.lower(MemoryEventRecord.value) == old_value.strip().lower()
                )
            if old_subject.strip():
                stmt = stmt.where(
                    MemoryEventRecord.subject == normalize_memory_token(old_subject)
                )
            if old_type.strip():
                stmt = stmt.where(
                    MemoryEventRecord.type == normalize_memory_token(old_type)
                )
            if not any([old_value.strip(), old_subject.strip(), old_type.strip()]):
                return None
        result = await self.session.execute(
            stmt.order_by(MemoryEventRecord.updated_at.desc()).limit(1)
        )
        target = result.scalar_one_or_none()
        if target is not None or memory_id is not None or not old_value.strip():
            return target

        fuzzy_stmt = self._active_events_stmt(user_id).where(
            self._memory_text_filter(old_value)
        )
        if old_subject.strip():
            fuzzy_stmt = fuzzy_stmt.where(
                MemoryEventRecord.subject == normalize_memory_token(old_subject)
            )
        if old_type.strip():
            fuzzy_stmt = fuzzy_stmt.where(
                MemoryEventRecord.type == normalize_memory_token(old_type)
            )
        result = await self.session.execute(
            fuzzy_stmt.order_by(MemoryEventRecord.updated_at.desc()).limit(1)
        )
        return result.scalar_one_or_none()

    async def _find_forget_targets(
        self,
        *,
        user_id: UUID,
        memory_id: UUID | None,
        subject: str,
        value: str,
        memory_type: str,
        thread_id: UUID | None,
    ) -> list[MemoryEventRecord]:
        stmt = self._active_events_stmt(user_id)
        if memory_id is not None:
            stmt = stmt.where(MemoryEventRecord.id == memory_id)
        else:
            if subject.strip():
                stmt = stmt.where(
                    MemoryEventRecord.subject == normalize_memory_token(subject)
                )
            if value.strip():
                stmt = stmt.where(self._memory_text_filter(value))
            if memory_type.strip():
                stmt = stmt.where(
                    MemoryEventRecord.type == normalize_memory_token(memory_type)
                )
            if thread_id is not None:
                stmt = stmt.where(MemoryEventRecord.thread_id == thread_id)
            if not any([subject.strip(), value.strip(), memory_type.strip(), memory_id]):
                return []
        result = await self.session.execute(
            stmt.order_by(MemoryEventRecord.updated_at.desc()).limit(50)
        )
        return list(result.scalars().all())

    def _memory_text_filter(self, query: str):
        predicates = []
        for term in _query_terms(query):
            pattern = f"%{term}%"
            predicates.extend(
                [
                    MemoryEventRecord.value.ilike(pattern),
                    MemoryEventRecord.subject.ilike(pattern),
                    cast(MemoryEventRecord.metadata_json, String).ilike(pattern),
                ]
            )
        if not predicates:
            pattern = f"%{query.strip()}%"
            predicates = [
                MemoryEventRecord.value.ilike(pattern),
                MemoryEventRecord.subject.ilike(pattern),
                cast(MemoryEventRecord.metadata_json, String).ilike(pattern),
            ]
        return or_(*predicates)

    async def _supersede_conflicts(self, record: MemoryEventRecord) -> None:
        if record.type not in _PROFILE_TYPES:
            return
        result = await self.session.execute(
            self._active_events_stmt(record.user_id)
            .where(
                MemoryEventRecord.id != record.id,
                MemoryEventRecord.type.in_(list(_PROFILE_TYPES)),
                MemoryEventRecord.subject == record.subject,
                func.lower(MemoryEventRecord.value) == record.value.lower(),
                MemoryEventRecord.polarity != record.polarity,
            )
            .limit(50)
        )
        conflicts = list(result.scalars().all())
        for conflict in conflicts:
            conflict.superseded_by = record.id
            conflict.updated_at = utc_now()
            await self._remove_event_from_profile(conflict)

    async def _apply_event_to_profile(self, record: MemoryEventRecord) -> None:
        if record.type not in _PROFILE_TYPES:
            return
        profile = await get_or_create_preference_profile(self.session, record.user_id)
        value = record.value.strip()
        if not value:
            return

        profile_summary = (record.metadata_json or {}).get("profile_summary")
        if isinstance(profile_summary, str) and profile_summary.strip():
            profile.profile_summary = profile_summary.strip()

        note = (record.metadata_json or {}).get("note") or self._profile_note(record)
        if note:
            notes = [line.strip() for line in profile.notes.splitlines() if line.strip()]
            if note not in notes:
                profile.notes = "\n".join([*notes, note]).strip()

        if record.subject in _AUTHOR_SUBJECTS:
            if record.polarity in _LIKE_POLARITIES:
                profile.favorite_authors = _add_unique(profile.favorite_authors, value)
                profile.disliked_authors = _remove_value(profile.disliked_authors, value)
            elif record.polarity in _DISLIKE_POLARITIES:
                profile.disliked_authors = _add_unique(profile.disliked_authors, value)
                profile.favorite_authors = _remove_value(profile.favorite_authors, value)
        elif record.subject in _TAG_SUBJECTS:
            if record.polarity in _LIKE_POLARITIES:
                profile.preferred_tags = _add_unique(profile.preferred_tags, value)
                profile.disliked_tags = _remove_value(profile.disliked_tags, value)
            elif record.polarity in _DISLIKE_POLARITIES:
                profile.disliked_tags = _add_unique(profile.disliked_tags, value)
                profile.preferred_tags = _remove_value(profile.preferred_tags, value)

    async def _remove_event_from_profile(self, record: MemoryEventRecord) -> None:
        if record.type not in _PROFILE_TYPES:
            return
        profile = await get_or_create_preference_profile(self.session, record.user_id)
        value = record.value.strip()
        if not value:
            return
        metadata = record.metadata_json or {}
        notes_to_remove = {self._profile_note(record)}
        metadata_note = metadata.get("note")
        if isinstance(metadata_note, str) and metadata_note.strip():
            notes_to_remove.add(metadata_note.strip())
        profile.notes = "\n".join(
            line
            for line in [item.strip() for item in profile.notes.splitlines()]
            if line
            and line not in notes_to_remove
            and value.lower() not in line.lower()
        )
        profile_summary = metadata.get("profile_summary")
        if (
            isinstance(profile_summary, str)
            and profile_summary.strip()
            and profile.profile_summary.strip() == profile_summary.strip()
        ):
            profile.profile_summary = ""
        elif value.lower() in profile.profile_summary.lower():
            profile.profile_summary = ""
        if record.subject in _AUTHOR_SUBJECTS:
            profile.favorite_authors = _remove_value(profile.favorite_authors, value)
            profile.disliked_authors = _remove_value(profile.disliked_authors, value)
        elif record.subject in _TAG_SUBJECTS:
            profile.preferred_tags = _remove_value(profile.preferred_tags, value)
            profile.disliked_tags = _remove_value(profile.disliked_tags, value)

    async def _mark_related_book_interaction_forgotten(
        self, record: MemoryEventRecord
    ) -> None:
        interaction_id = (record.metadata_json or {}).get("interaction_id")
        if not interaction_id:
            return
        try:
            interaction_uuid = UUID(str(interaction_id))
        except ValueError:
            return
        result = await self.session.execute(
            select(BookInteraction).where(
                BookInteraction.id == interaction_uuid,
                BookInteraction.user_id == record.user_id,
            )
        )
        interaction = result.scalar_one_or_none()
        if interaction is None:
            return
        raw_data = dict(interaction.raw_data or {})
        raw_data["memory_forgotten"] = True
        raw_data["forgotten_memory_event_id"] = str(record.id)
        raw_data["memory_forgotten_at"] = utc_now().isoformat()
        interaction.raw_data = raw_data
        interaction.updated_at = utc_now()

    def _normalize_event(self, event: MemoryEvent) -> MemoryEvent:
        return MemoryEvent.model_validate(event.model_dump())

    def _record_from_event(self, event: MemoryEvent) -> MemoryEventRecord:
        return MemoryEventRecord(
            user_id=event.user_id,
            thread_id=event.thread_id,
            type=event.type,
            subject=event.subject,
            value=event.value,
            polarity=event.polarity,
            confidence=event.confidence,
            source=event.source,
            metadata_json=event.metadata,
            revision_of=event.revision_of,
        )

    def _event_from_record(self, record: MemoryEventRecord) -> MemoryEvent:
        return MemoryEvent(
            id=record.id,
            type=record.type,
            subject=record.subject,
            value=record.value,
            polarity=record.polarity,
            confidence=record.confidence,
            user_id=record.user_id,
            thread_id=record.thread_id,
            source=record.source,
            metadata=record.metadata_json or {},
            revision_of=record.revision_of,
            superseded_by=record.superseded_by,
            forgotten=record.is_deleted,
            created_at=record.created_at,
            updated_at=record.updated_at,
        )

    def _build_reading_states(
        self,
        events: list[MemoryEventRecord],
        interactions: list[BookInteraction],
    ) -> list[dict[str, Any]]:
        states: list[dict[str, Any]] = []
        for event in events:
            if event.type in _READING_TYPES or event.polarity in _READING_POLARITIES:
                states.append(
                    {
                        "source": "memory_event",
                        "event_id": str(event.id),
                        "subject": event.subject,
                        "value": event.value,
                        "polarity": event.polarity,
                        "created_at": event.created_at.isoformat(),
                    }
                )
        for interaction in interactions:
            states.append(
                {
                    "source": "book_interaction",
                    "interaction_id": str(interaction.id),
                    "book_id": str(interaction.book_id)
                    if interaction.book_id
                    else None,
                    "book_title": interaction.book_title,
                    "interaction_type": interaction.interaction_type,
                    "rating": interaction.rating,
                    "note": interaction.note,
                    "created_at": interaction.created_at.isoformat(),
                }
            )
        return states

    def _profile_note(self, record: MemoryEventRecord) -> str:
        if record.polarity in _LIKE_POLARITIES:
            return f"Likes {record.subject}: {record.value}"
        if record.polarity in _DISLIKE_POLARITIES:
            return f"Dislikes {record.subject}: {record.value}"
        return f"{record.type} {record.subject}: {record.value}"
