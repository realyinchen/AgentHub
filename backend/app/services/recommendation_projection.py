from __future__ import annotations

import math
import re
from collections.abc import Sequence
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.crud.book import get_or_create_preference_profile
from app.models.book import Book, BookInteraction, RecommendationEvent
from app.services.recommendation_signals import (
    NEGATIVE_EVENT_TYPES,
    READING_STATE_EVENT_TYPES,
    SUPPRESSION_EVENT_TYPES,
    normalize_recommendation_text,
    normalize_recommendation_token,
)


PROJECTION_CONTRACT_VERSION = "recommendation-projection-v1"
DEFAULT_ATTENTION_HALF_LIFE_DAYS = 30.0
_WORD_RE = re.compile(r"[\w\u4e00-\u9fff]+", re.IGNORECASE)
_QUERY_STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "book",
    "books",
    "for",
    "i",
    "me",
    "novel",
    "novels",
    "of",
    "or",
    "please",
    "recommend",
    "the",
    "to",
}


class RecommendationProjectionFeature(BaseModel):
    source: str
    key: str
    value: str = ""
    score_delta: float = 0.0
    weight: float = 1.0
    reason: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)


class RecommendationCandidateProjection(BaseModel):
    book_id: UUID | None = None
    book_title: str
    score: float = 0.0
    base_score: float = 0.0
    memory_score: float = 0.0
    behavior_score: float = 0.0
    query_score: float = 0.0
    suppressed: bool = False
    suppression_reasons: list[str] = Field(default_factory=list)
    positive_reasons: list[str] = Field(default_factory=list)
    negative_reasons: list[str] = Field(default_factory=list)
    features: list[RecommendationProjectionFeature] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class RecommendationProjectionResult(BaseModel):
    user_id: UUID
    query: str = ""
    candidates: list[RecommendationCandidateProjection] = Field(default_factory=list)
    suppressed_candidates: list[RecommendationCandidateProjection] = Field(
        default_factory=list
    )
    metadata: dict[str, Any] = Field(default_factory=dict)


class RecommendationProjector:
    """Build app-owned recommendation ranking features without writing state."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        attention_half_life_days: float = DEFAULT_ATTENTION_HALF_LIFE_DAYS,
    ) -> None:
        self.session = session
        self.attention_half_life_days = max(1.0, attention_half_life_days)

    async def project_books(
        self,
        *,
        user_id: UUID,
        query: str,
        books: Sequence[Book],
    ) -> RecommendationProjectionResult:
        profile = await get_or_create_preference_profile(self.session, user_id)
        events = await self._load_events(user_id)
        interactions = await self._load_interactions(user_id)
        now = datetime.now(timezone.utc)

        candidates: list[RecommendationCandidateProjection] = []
        suppressed: list[RecommendationCandidateProjection] = []
        for index, book in enumerate(books):
            projection = self._project_book(
                user_id=user_id,
                query=query,
                book=book,
                rank_index=index,
                preferred_tags=list(profile.preferred_tags or []),
                disliked_tags=list(profile.disliked_tags or []),
                favorite_authors=list(profile.favorite_authors or []),
                disliked_authors=list(profile.disliked_authors or []),
                events=events,
                interactions=interactions,
                now=now,
            )
            if projection.suppressed:
                suppressed.append(projection)
            else:
                candidates.append(projection)

        candidates.sort(key=lambda item: item.score, reverse=True)
        suppressed.sort(key=lambda item: item.score, reverse=True)
        return RecommendationProjectionResult(
            user_id=user_id,
            query=query,
            candidates=candidates,
            suppressed_candidates=suppressed,
            metadata={
                "contract_version": PROJECTION_CONTRACT_VERSION,
                "attention_half_life_days": self.attention_half_life_days,
                "candidate_count": len(candidates),
                "suppressed_count": len(suppressed),
            },
        )

    async def _load_events(self, user_id: UUID) -> list[RecommendationEvent]:
        result = await self.session.execute(
            select(RecommendationEvent)
            .where(RecommendationEvent.user_id == user_id)
            .order_by(RecommendationEvent.created_at.desc())
            .limit(500)
        )
        return list(result.scalars().all())

    async def _load_interactions(self, user_id: UUID) -> list[BookInteraction]:
        result = await self.session.execute(
            select(BookInteraction)
            .where(BookInteraction.user_id == user_id)
            .order_by(BookInteraction.created_at.desc())
            .limit(500)
        )
        return list(result.scalars().all())

    def _project_book(
        self,
        *,
        user_id: UUID,
        query: str,
        book: Book,
        rank_index: int,
        preferred_tags: list[str],
        disliked_tags: list[str],
        favorite_authors: list[str],
        disliked_authors: list[str],
        events: list[RecommendationEvent],
        interactions: list[BookInteraction],
        now: datetime,
    ) -> RecommendationCandidateProjection:
        title = normalize_recommendation_text(book.title)
        projection = RecommendationCandidateProjection(
            book_id=book.id,
            book_title=title,
            base_score=max(0.0, 1.0 - rank_index * 0.05),
            metadata={
                "contract_version": PROJECTION_CONTRACT_VERSION,
                "source_rank": rank_index,
                "user_id": str(user_id),
            },
        )
        projection.score += projection.base_score

        self._apply_query_features(projection, query=query, book=book)
        self._apply_memory_features(
            projection,
            book=book,
            preferred_tags=preferred_tags,
            disliked_tags=disliked_tags,
            favorite_authors=favorite_authors,
            disliked_authors=disliked_authors,
        )
        self._apply_behavior_features(
            projection,
            book=book,
            events=events,
            interactions=interactions,
            now=now,
        )
        projection.score = round(
            projection.base_score
            + projection.memory_score
            + projection.behavior_score
            + projection.query_score,
            4,
        )
        return projection

    def _apply_query_features(
        self,
        projection: RecommendationCandidateProjection,
        *,
        query: str,
        book: Book,
    ) -> None:
        haystack = _book_text(book)
        matched_terms = [
            term for term in _query_terms(query) if term.lower() in haystack
        ][:8]
        if not matched_terms:
            return
        delta = min(0.25, 0.04 * len(matched_terms))
        projection.query_score += delta
        projection.positive_reasons.append(
            f"matches query terms: {', '.join(matched_terms)}"
        )
        projection.features.append(
            RecommendationProjectionFeature(
                source="query",
                key="matched_terms",
                value=", ".join(matched_terms),
                score_delta=delta,
                reason="candidate text matches current recommendation query",
            )
        )

    def _apply_memory_features(
        self,
        projection: RecommendationCandidateProjection,
        *,
        book: Book,
        preferred_tags: list[str],
        disliked_tags: list[str],
        favorite_authors: list[str],
        disliked_authors: list[str],
    ) -> None:
        haystack = _book_text(book)
        authors = {
            str(author).strip().lower()
            for author in getattr(book, "authors", None) or []
        }

        for value in preferred_tags:
            token = value.strip()
            if token and token.lower() in haystack:
                self._add_memory_feature(
                    projection,
                    key="preferred_tag",
                    value=token,
                    delta=0.18,
                    positive=True,
                )
        for value in disliked_tags:
            token = value.strip()
            if token and token.lower() in haystack:
                self._add_memory_feature(
                    projection,
                    key="disliked_tag",
                    value=token,
                    delta=-0.35,
                    positive=False,
                )
        for author in favorite_authors:
            token = author.strip()
            if token and token.lower() in authors:
                self._add_memory_feature(
                    projection,
                    key="favorite_author",
                    value=token,
                    delta=0.3,
                    positive=True,
                )
        for author in disliked_authors:
            token = author.strip()
            if token and token.lower() in authors:
                self._add_memory_feature(
                    projection,
                    key="disliked_author",
                    value=token,
                    delta=-0.55,
                    positive=False,
                )

    def _add_memory_feature(
        self,
        projection: RecommendationCandidateProjection,
        *,
        key: str,
        value: str,
        delta: float,
        positive: bool,
    ) -> None:
        projection.memory_score += delta
        if positive:
            projection.positive_reasons.append(f"matches memory {key}: {value}")
        else:
            projection.negative_reasons.append(f"conflicts with memory {key}: {value}")
        projection.features.append(
            RecommendationProjectionFeature(
                source="long_term_memory",
                key=key,
                value=value,
                score_delta=delta,
                reason=(
                    "candidate matches active preference"
                    if positive
                    else "candidate conflicts with active preference"
                ),
            )
        )

    def _apply_behavior_features(
        self,
        projection: RecommendationCandidateProjection,
        *,
        book: Book,
        events: list[RecommendationEvent],
        interactions: list[BookInteraction],
        now: datetime,
    ) -> None:
        for interaction in interactions:
            if not _same_book(book, interaction.book_id, interaction.book_title):
                continue
            event_type = normalize_recommendation_token(interaction.interaction_type)
            delta = _interaction_delta(event_type)
            if event_type in {"read", "finished", "already_read"}:
                projection.suppressed = True
                projection.suppression_reasons.append("already_read")
            elif event_type in {"dislike", "disliked", "not_interested", "avoid"}:
                projection.suppressed = True
                projection.suppression_reasons.append("negative_book_feedback")
            if delta:
                projection.behavior_score += delta
                projection.features.append(
                    RecommendationProjectionFeature(
                        source="book_interaction",
                        key=event_type,
                        value=interaction.book_title or "",
                        score_delta=delta,
                        reason="explicit book feedback",
                    )
                )

        for event in events:
            if not _same_book(book, event.book_id, event.book_title):
                continue
            event_type = normalize_recommendation_token(event.event_type)
            strength = _to_float(event.signal_strength)
            decay = _decay_multiplier(event.created_at, now, self.attention_half_life_days)
            delta = _event_delta(event_type, event.signal_polarity, strength) * decay
            if event_type in READING_STATE_EVENT_TYPES:
                projection.suppressed = True
                projection.suppression_reasons.append("already_read")
            elif event_type in NEGATIVE_EVENT_TYPES:
                projection.suppressed = True
                projection.suppression_reasons.append("negative_recommendation_signal")
            elif event_type in SUPPRESSION_EVENT_TYPES:
                projection.suppressed = True
                projection.suppression_reasons.append(f"suppressed_by_{event_type}")
            if delta:
                projection.behavior_score += delta
                if delta > 0:
                    projection.positive_reasons.append(
                        f"recent behavior signal: {event_type}"
                    )
                else:
                    projection.negative_reasons.append(
                        f"negative behavior signal: {event_type}"
                    )
                projection.features.append(
                    RecommendationProjectionFeature(
                        source="recommendation_event",
                        key=event_type,
                        value=event.book_title or "",
                        score_delta=round(delta, 4),
                        weight=round(decay, 4),
                        reason="decayed recommendation behavior signal",
                        metadata={
                            "event_id": str(event.id),
                            "raw_strength": strength,
                            "created_at": event.created_at.isoformat()
                            if event.created_at
                            else None,
                        },
                    )
                )

        projection.suppression_reasons = _unique(projection.suppression_reasons)
        projection.positive_reasons = _unique(projection.positive_reasons)
        projection.negative_reasons = _unique(projection.negative_reasons)


def _book_text(book: Book) -> str:
    parts = [
        getattr(book, "title", ""),
        getattr(book, "subtitle", ""),
        " ".join(getattr(book, "authors", None) or []),
        " ".join(getattr(book, "tags", None) or []),
        getattr(book, "summary", ""),
        str(getattr(book, "raw_data", None) or ""),
    ]
    return " ".join(str(part or "") for part in parts).lower()


def _query_terms(query: str, max_terms: int = 12) -> list[str]:
    terms: list[str] = []
    seen: set[str] = set()
    for match in _WORD_RE.findall(query.lower()):
        if len(match) < 2 or match in _QUERY_STOPWORDS or match in seen:
            continue
        seen.add(match)
        terms.append(match)
        if len(terms) >= max_terms:
            break
    return terms


def _same_book(book: Book, book_id: UUID | None, book_title: str | None) -> bool:
    if book_id is not None and getattr(book, "id", None) == book_id:
        return True
    title = normalize_recommendation_text(getattr(book, "title", "")).lower()
    other_title = normalize_recommendation_text(book_title).lower()
    return bool(title and other_title and title == other_title)


def _interaction_delta(event_type: str) -> float:
    if event_type in {"want", "want_to_read", "to_read"}:
        return 0.45
    if event_type in {"like", "liked", "similar"}:
        return 0.5
    if event_type in {"read", "finished", "already_read"}:
        return -1.0
    if event_type in {"dislike", "disliked", "not_interested", "avoid"}:
        return -0.8
    return 0.0


def _event_delta(event_type: str, polarity: str, strength: float) -> float:
    if event_type in {"detail_requested", "followup_clicked", "followup_matched"}:
        return max(0.0, strength) * 0.35
    if event_type == "want_to_read":
        return max(0.0, strength) * 0.5
    if event_type == "liked":
        return max(0.0, strength) * 0.55
    if event_type == "recommended":
        return max(0.0, strength) * 0.08
    if event_type == "read":
        return -1.0
    if event_type in {"disliked", "not_interested", "suppressed"}:
        return -0.75 * max(0.2, strength)
    if polarity == "positive":
        return max(0.0, strength) * 0.2
    if polarity == "negative":
        return -0.2 * max(0.2, strength)
    return 0.0


def _decay_multiplier(
    created_at: datetime | None,
    now: datetime,
    half_life_days: float,
) -> float:
    if created_at is None:
        return 1.0
    event_time = created_at
    if event_time.tzinfo is None:
        event_time = event_time.replace(tzinfo=timezone.utc)
    age_seconds = max(0.0, (now - event_time).total_seconds())
    age_days = age_seconds / 86400
    return float(math.pow(0.5, age_days / half_life_days))


def _to_float(value: Any) -> float:
    if isinstance(value, Decimal):
        return float(value)
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        key = value.strip().lower()
        if key and key not in seen:
            seen.add(key)
            result.append(value)
    return result
