from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


RECOMMENDATION_EVENT_TYPES = frozenset(
    {
        "candidate_retrieved",
        "recommended",
        "followup_suggested",
        "followup_clicked",
        "followup_matched",
        "detail_requested",
        "want_to_read",
        "read",
        "liked",
        "disliked",
        "not_interested",
        "suppressed",
    }
)
RECOMMENDATION_SIGNAL_POLARITIES = frozenset(
    {"positive", "negative", "neutral"}
)
RECOMMENDATION_SIGNAL_SOURCES = frozenset(
    {"agent_tool", "book_feedback", "followup_question", "api", "system"}
)

READING_STATE_EVENT_TYPES = frozenset({"read"})
NEGATIVE_EVENT_TYPES = frozenset({"disliked", "not_interested"})
SUPPRESSION_EVENT_TYPES = READING_STATE_EVENT_TYPES | NEGATIVE_EVENT_TYPES


def normalize_recommendation_token(value: Any) -> str:
    return str(value or "").strip().lower().replace(" ", "_")


def normalize_recommendation_text(value: Any) -> str:
    return str(value or "").strip()


def validate_recommendation_token(
    field_name: str,
    value: Any,
    allowed: frozenset[str],
) -> str:
    token = normalize_recommendation_token(value)
    if token not in allowed:
        allowed_values = ", ".join(sorted(allowed))
        raise ValueError(f"{field_name} must be one of: {allowed_values}")
    return token


class FollowUpQuestion(BaseModel):
    """Candidate next question shown to the user but not treated as memory."""

    id: str
    question: str
    reason: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("id", "question", "reason", mode="before")
    @classmethod
    def clean_text(cls, value: Any) -> str:
        return normalize_recommendation_text(value)


class RecommendationSignalCreate(BaseModel):
    """App-owned event contract for recommendation behavior signals."""

    user_id: UUID
    event_type: str
    signal_polarity: str = "neutral"
    signal_strength: float = Field(default=0.0, ge=0.0, le=1.0)
    book_id: UUID | None = None
    book_title: str = ""
    thread_id: UUID | None = None
    request_id: str = ""
    message_id: str = ""
    source: str = "agent_tool"
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("event_type", mode="before")
    @classmethod
    def validate_event_type(cls, value: Any) -> str:
        return validate_recommendation_token(
            "event_type",
            value,
            RECOMMENDATION_EVENT_TYPES,
        )

    @field_validator("signal_polarity", mode="before")
    @classmethod
    def validate_signal_polarity(cls, value: Any) -> str:
        return validate_recommendation_token(
            "signal_polarity",
            value,
            RECOMMENDATION_SIGNAL_POLARITIES,
        )

    @field_validator("source", mode="before")
    @classmethod
    def validate_source(cls, value: Any) -> str:
        return validate_recommendation_token(
            "source",
            value,
            RECOMMENDATION_SIGNAL_SOURCES,
        )

    @field_validator("book_title", "request_id", "message_id", mode="before")
    @classmethod
    def clean_optional_text(cls, value: Any) -> str:
        return normalize_recommendation_text(value)


class RecommendationSignal(RecommendationSignalCreate):
    id: UUID
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


def recommendation_signal_from_record(record: Any) -> RecommendationSignal:
    """Map ORM implementation fields into the app-owned signal contract."""

    return RecommendationSignal(
        id=record.id,
        user_id=record.user_id,
        thread_id=record.thread_id,
        request_id=record.request_id or "",
        message_id=record.message_id or "",
        book_id=record.book_id,
        book_title=record.book_title or "",
        event_type=record.event_type,
        signal_polarity=record.signal_polarity,
        signal_strength=float(record.signal_strength or 0.0),
        source=record.source,
        metadata=record.metadata_json or {},
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


class RecommendationFeedbackPlan(BaseModel):
    event_type: str
    signal_polarity: str
    signal_strength: float = Field(ge=0.0, le=1.0)
    writes_long_term_memory: bool = False

    @field_validator("event_type", mode="before")
    @classmethod
    def validate_event_type(cls, value: Any) -> str:
        return validate_recommendation_token(
            "event_type",
            value,
            RECOMMENDATION_EVENT_TYPES,
        )

    @field_validator("signal_polarity", mode="before")
    @classmethod
    def validate_signal_polarity(cls, value: Any) -> str:
        return validate_recommendation_token(
            "signal_polarity",
            value,
            RECOMMENDATION_SIGNAL_POLARITIES,
        )


def map_interaction_to_recommendation_signal(
    interaction_type: str,
) -> RecommendationFeedbackPlan:
    normalized = normalize_recommendation_token(interaction_type)
    if normalized in {"read", "finished", "already_read"}:
        return RecommendationFeedbackPlan(
            event_type="read",
            signal_polarity="neutral",
            signal_strength=1.0,
            writes_long_term_memory=True,
        )
    if normalized in {"want", "want_to_read", "to_read"}:
        return RecommendationFeedbackPlan(
            event_type="want_to_read",
            signal_polarity="positive",
            signal_strength=0.75,
            writes_long_term_memory=True,
        )
    if normalized in {"like", "liked", "similar"}:
        return RecommendationFeedbackPlan(
            event_type="liked",
            signal_polarity="positive",
            signal_strength=0.85,
            writes_long_term_memory=True,
        )
    if normalized in {"dislike", "disliked"}:
        return RecommendationFeedbackPlan(
            event_type="disliked",
            signal_polarity="negative",
            signal_strength=0.9,
            writes_long_term_memory=True,
        )
    if normalized in {"not_interested", "avoid"}:
        return RecommendationFeedbackPlan(
            event_type="not_interested",
            signal_polarity="negative",
            signal_strength=0.8,
            writes_long_term_memory=True,
        )
    if normalized in {"continue", "tell_me_more", "detail_requested"}:
        return RecommendationFeedbackPlan(
            event_type="detail_requested",
            signal_polarity="positive",
            signal_strength=0.55,
            writes_long_term_memory=False,
        )
    return RecommendationFeedbackPlan(
        event_type="recommended",
        signal_polarity="neutral",
        signal_strength=0.1,
        writes_long_term_memory=False,
    )


def build_follow_up_questions(
    *,
    query: str,
    books: list[dict[str, Any]],
) -> list[FollowUpQuestion]:
    """Return bounded follow-up options; these are temporary recommendation UI state."""

    first_title = normalize_recommendation_text(books[0].get("title")) if books else ""
    if first_title:
        return [
            FollowUpQuestion(
                id="detail_first_book",
                question=f"Tell me more about why {first_title} fits me.",
                reason="positive attention signal if selected",
                metadata={"book_title": first_title},
            ),
            FollowUpQuestion(
                id="compare_candidates",
                question="Compare these options by style, pacing, and emotional intensity.",
                reason="comparison signal across current candidates",
            ),
            FollowUpQuestion(
                id="refine_constraints",
                question="Refine this list toward books that are warmer and more character-driven.",
                reason="preference-refinement signal",
            ),
        ]

    topic = normalize_recommendation_text(query) or "this reading direction"
    return [
        FollowUpQuestion(
            id="clarify_style",
            question=f"What traits define {topic}?",
            reason="style clarification",
        ),
        FollowUpQuestion(
            id="ask_recommendations",
            question=f"Recommend books close to {topic}.",
            reason="explicit recommendation intent if selected",
        ),
        FollowUpQuestion(
            id="narrow_constraints",
            question="Narrow this by warmth, difficulty, length, or emotional intensity.",
            reason="constraint refinement",
        ),
    ]
