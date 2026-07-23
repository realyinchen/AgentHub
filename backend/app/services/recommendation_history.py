from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.book import BookInteraction, RecommendationEvent
from app.services.recommendation_signals import (
    RECOMMENDATION_EVENT_TYPES,
    SUPPRESSION_EVENT_TYPES,
    normalize_recommendation_text,
    normalize_recommendation_token,
)


RECOMMENDATION_HISTORY_CONTRACT_VERSION = "recommendation-history-v1"
RECOMMENDATION_HISTORY_MODES = frozenset(
    {
        "all",
        "reading_history",
        "rejection_history",
        "suppression_explanation",
    }
)
RECOMMENDATION_HISTORY_STATUSES = frozenset({"ok", "empty_result"})

_READING_INTERACTION_TYPES = frozenset({"read", "finished", "already_read"})
_NEGATIVE_INTERACTION_TYPES = frozenset(
    {"dislike", "disliked", "not_interested", "avoid"}
)
_SUPPRESSION_EVENT_TYPES = frozenset({*SUPPRESSION_EVENT_TYPES, "suppressed"})


class RecommendationHistoryRecord(BaseModel):
    """App-owned view of a recommendation-history or suppression record."""

    record_type: str
    event_type: str
    book_id: UUID | None = None
    book_title: str = ""
    reason: str = ""
    suppression_reasons: list[str] = Field(default_factory=list)
    signal_polarity: str = "neutral"
    signal_strength: float = 0.0
    source: str = ""
    thread_id: UUID | None = None
    request_id: str = ""
    message_id: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime | None = None


class RecommendationHistoryResult(BaseModel):
    """Result contract for explicit history/explanation turns."""

    status: str = "ok"
    result_mode: str = "recommendation_history"
    history_mode: str = "all"
    user_id: UUID
    query: str = ""
    book_title: str = ""
    records: list[RecommendationHistoryRecord] = Field(default_factory=list)
    suppressed_records: list[RecommendationHistoryRecord] = Field(default_factory=list)
    result_count: int = 0
    next_action_hint: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)


def normalize_recommendation_history_mode(value: Any) -> str:
    mode = normalize_recommendation_token(value)
    return mode if mode in RECOMMENDATION_HISTORY_MODES else "all"


async def get_recommendation_history(
    session: AsyncSession,
    *,
    user_id: UUID,
    history_mode: str = "all",
    query: str = "",
    book_title: str = "",
    limit: int = 20,
) -> RecommendationHistoryResult:
    """Return read-only recommendation history and suppression records."""

    mode = normalize_recommendation_history_mode(history_mode)
    title_filter = normalize_recommendation_text(book_title)
    bounded_limit = max(1, min(int(limit or 20), 50))

    event_records = [
        _record_from_event(event)
        for event in await _load_recommendation_events(
            session,
            user_id=user_id,
            history_mode=mode,
            book_title=title_filter,
            limit=bounded_limit * 2,
        )
    ]
    seen = {_dedupe_key(record) for record in event_records}
    interaction_records: list[RecommendationHistoryRecord] = []
    for interaction in await _load_book_interactions(
        session,
        user_id=user_id,
        history_mode=mode,
        book_title=title_filter,
        limit=bounded_limit * 2,
    ):
        record = _record_from_interaction(interaction)
        if record is None:
            continue
        key = _dedupe_key(record)
        if key in seen:
            continue
        seen.add(key)
        interaction_records.append(record)

    records = sorted(
        [*event_records, *interaction_records],
        key=lambda item: item.created_at.timestamp() if item.created_at else 0.0,
        reverse=True,
    )[:bounded_limit]
    suppressed_records = [
        record for record in records if record.suppression_reasons
    ]
    status = "ok" if records else "empty_result"
    return RecommendationHistoryResult(
        status=status,
        history_mode=mode,
        user_id=user_id,
        query=normalize_recommendation_text(query),
        book_title=title_filter,
        records=records,
        suppressed_records=suppressed_records,
        result_count=len(records),
        next_action_hint=_next_action_hint(status, mode),
        metadata={
            "contract_version": RECOMMENDATION_HISTORY_CONTRACT_VERSION,
            "suppressed_records_are_history_only": True,
            "ordinary_recommendation_candidates": False,
            "record_sources": ["recommendation_events", "book_interactions"],
        },
    )


async def _load_recommendation_events(
    session: AsyncSession,
    *,
    user_id: UUID,
    history_mode: str,
    book_title: str,
    limit: int,
) -> list[RecommendationEvent]:
    stmt = select(RecommendationEvent).where(
        RecommendationEvent.user_id == user_id,
        RecommendationEvent.event_type.in_(list(_event_types_for_mode(history_mode))),
    )
    if book_title:
        stmt = stmt.where(RecommendationEvent.book_title.ilike(f"%{book_title}%"))
    result = await session.execute(
        stmt.order_by(RecommendationEvent.created_at.desc()).limit(limit)
    )
    return list(result.scalars().all())


async def _load_book_interactions(
    session: AsyncSession,
    *,
    user_id: UUID,
    history_mode: str,
    book_title: str,
    limit: int,
) -> list[BookInteraction]:
    stmt = select(BookInteraction).where(
        BookInteraction.user_id == user_id,
        BookInteraction.interaction_type.in_(
            list(_interaction_types_for_mode(history_mode))
        ),
    )
    if book_title:
        stmt = stmt.where(BookInteraction.book_title.ilike(f"%{book_title}%"))
    result = await session.execute(
        stmt.order_by(BookInteraction.created_at.desc()).limit(limit)
    )
    return list(result.scalars().all())


def _event_types_for_mode(history_mode: str) -> set[str]:
    if history_mode == "reading_history":
        return {"read"}
    if history_mode == "rejection_history":
        return {"disliked", "not_interested", "suppressed"}
    return set(_SUPPRESSION_EVENT_TYPES)


def _interaction_types_for_mode(history_mode: str) -> set[str]:
    if history_mode == "reading_history":
        return set(_READING_INTERACTION_TYPES)
    if history_mode == "rejection_history":
        return set(_NEGATIVE_INTERACTION_TYPES)
    return {*_READING_INTERACTION_TYPES, *_NEGATIVE_INTERACTION_TYPES}


def _record_from_event(event: RecommendationEvent) -> RecommendationHistoryRecord:
    event_type = _canonical_event_type(event.event_type)
    return RecommendationHistoryRecord(
        record_type="recommendation_event",
        event_type=event_type,
        book_id=event.book_id,
        book_title=normalize_recommendation_text(event.book_title),
        reason=_reason_for_event_type(event_type),
        suppression_reasons=_suppression_reasons_for_event_type(event_type),
        signal_polarity=normalize_recommendation_token(event.signal_polarity)
        or "neutral",
        signal_strength=float(event.signal_strength or 0.0),
        source=normalize_recommendation_token(event.source) or "agent_tool",
        thread_id=event.thread_id,
        request_id=event.request_id or "",
        message_id=event.message_id or "",
        metadata=event.metadata_json or {},
        created_at=event.created_at,
    )


def _record_from_interaction(
    interaction: BookInteraction,
) -> RecommendationHistoryRecord | None:
    event_type = _canonical_interaction_event_type(interaction.interaction_type)
    if event_type is None:
        return None
    return RecommendationHistoryRecord(
        record_type="book_interaction",
        event_type=event_type,
        book_id=interaction.book_id,
        book_title=normalize_recommendation_text(interaction.book_title),
        reason=_reason_for_event_type(event_type),
        suppression_reasons=_suppression_reasons_for_event_type(event_type),
        signal_polarity="negative"
        if event_type in {"disliked", "not_interested", "suppressed"}
        else "neutral",
        signal_strength=1.0,
        source="book_feedback",
        metadata={
            "interaction_id": str(interaction.id),
            "interaction_type": interaction.interaction_type,
            "note": interaction.note or "",
            "rating": interaction.rating,
        },
        created_at=interaction.created_at,
    )


def _canonical_event_type(value: Any) -> str:
    token = normalize_recommendation_token(value)
    if token in RECOMMENDATION_EVENT_TYPES:
        return token
    return "suppressed"


def _canonical_interaction_event_type(value: Any) -> str | None:
    token = normalize_recommendation_token(value)
    if token in _READING_INTERACTION_TYPES:
        return "read"
    if token in {"dislike", "disliked"}:
        return "disliked"
    if token in {"not_interested", "avoid"}:
        return "not_interested"
    return None


def _suppression_reasons_for_event_type(event_type: str) -> list[str]:
    if event_type == "read":
        return ["already_read"]
    if event_type in {"disliked", "not_interested"}:
        return ["negative_recommendation_signal"]
    if event_type == "suppressed":
        return ["suppressed_by_system"]
    return []


def _reason_for_event_type(event_type: str) -> str:
    if event_type == "read":
        return "The user already read this book."
    if event_type == "disliked":
        return "The user gave negative feedback for this book."
    if event_type == "not_interested":
        return "The user marked this book as not interesting."
    if event_type == "suppressed":
        return "The recommendation system suppressed this book."
    return "Recommendation history record."


def _dedupe_key(record: RecommendationHistoryRecord) -> tuple[str, str]:
    return (record.book_title.strip().lower(), record.event_type)


def _next_action_hint(status: str, history_mode: str) -> str:
    if status == "empty_result":
        return (
            "No matching recommendation history records were found. Do not invent "
            "read, rejected, or suppressed books."
        )
    if history_mode == "suppression_explanation":
        return (
            "Explain these records as suppression/history context only. Do not "
            "turn them into fresh recommendation candidates."
        )
    return (
        "Use these records only to answer the explicit history request. Ordinary "
        "recommendations must continue to suppress these books."
    )
