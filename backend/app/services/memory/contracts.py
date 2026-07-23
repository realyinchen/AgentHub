from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator


MEMORY_TYPES = frozenset(
    {
        "state",
        "preference",
        "feedback",
        "reading_state",
        "entity",
        "correction",
        "forget",
    }
)
MEMORY_SUBJECTS = frozenset(
    {
        "user",
        "book",
        "author",
        "tag",
        "theme",
        "style",
        "genre",
        "mood",
        "pacing",
        "content",
        "pet",
        "person",
        "object",
        "entity",
    }
)
MEMORY_POLARITIES = frozenset(
    {
        "like",
        "dislike",
        "neutral",
        "want",
        "read",
        "avoid",
    }
)
MEMORY_SOURCES = frozenset({"chat_turn", "tool", "manual"})
INFORMATION_SCOPES = frozenset(
    {
        "long_term_memory",
        "short_term_thread_state",
        "temporary_turn_state",
        "research_state",
        "search_state",
    }
)
MEMORY_CANDIDATE_SOURCE_KINDS = frozenset(
    {
        "user_message",
        "book_feedback",
        "manual",
        "tool",
        "model_inference",
        "search_result",
        "research_evidence",
        "provider_raw",
        "thread_summary",
        "temporary_turn_state",
    }
)
MEMORY_ADMISSION_DECISIONS = frozenset(
    {"allow", "reject", "revise_existing", "needs_confirmation"}
)
MEMORY_CONFLICT_TYPES = frozenset(
    {
        "direct_polarity_conflict",
        "preference_refinement",
        "state_progression",
        "duplicate",
        "explicit_correction",
        "ambiguous_conflict",
    }
)
MEMORY_CONFLICT_SEVERITIES = frozenset({"low", "medium", "high"})
MEMORY_CONFLICT_DECISIONS = frozenset(
    {"allow", "skip_duplicate", "revise_existing", "needs_confirmation"}
)
MEMORY_PROVIDER_STATUSES = frozenset(
    {"completed", "empty_result", "timeout", "failed", "skipped"}
)
MEMORY_PROVIDER_STATUS_TO_CONTRACT = {
    "ok": "completed",
    "success": "completed",
    "completed": "completed",
    "empty": "empty_result",
    "empty_result": "empty_result",
    "no_result": "empty_result",
    "no_results": "empty_result",
    "timeout": "timeout",
    "timed_out": "timeout",
    "failed": "failed",
    "failure": "failed",
    "error": "failed",
    "hard_error": "failed",
    "rate_limited": "failed",
    "skipped": "skipped",
}
MEMORY_ENTITY_TYPES = frozenset({"pet", "person", "object", "entity"})
MEMORY_ENTITY_RELATIONS = frozenset(
    {"owns", "related_to", "uses", "cares_for"}
)
USER_STATE_CATEGORIES = frozenset(
    {"profile", "preference", "relation", "feedback", "short_term"}
)
USER_STATE_STATUSES = frozenset(
    {
        "pending",
        "active",
        "needs_confirmation",
        "superseded",
        "expired",
        "forgotten",
    }
)


def normalize_memory_token(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip().lower().replace(" ", "_")


def normalize_memory_value(value: Any) -> str:
    return str(value or "").strip()


def validate_memory_token(field_name: str, value: Any, allowed: frozenset[str]) -> str:
    token = normalize_memory_token(str(value or ""))
    if token not in allowed:
        allowed_values = ", ".join(sorted(allowed))
        raise ValueError(f"{field_name} must be one of: {allowed_values}")
    return token


def validate_optional_memory_token(
    field_name: str,
    value: Any,
    allowed: frozenset[str],
) -> str:
    token = normalize_memory_token(str(value or ""))
    if not token:
        return ""
    if token not in allowed:
        allowed_values = ", ".join(sorted(allowed))
        raise ValueError(f"{field_name} must be empty or one of: {allowed_values}")
    return token


def map_memory_provider_status(value: Any) -> str:
    token = normalize_memory_token(value)
    mapped = MEMORY_PROVIDER_STATUS_TO_CONTRACT.get(token, "failed")
    return validate_memory_token("status", mapped, MEMORY_PROVIDER_STATUSES)


class MemoryEntityFact(BaseModel):
    """Application-owned structured fact about an entity related to the user."""

    entity_type: str
    name: str = Field(min_length=1, max_length=80)
    relation: str = "related_to"
    attributes: dict[str, str] = Field(default_factory=dict)

    @field_validator("entity_type", mode="before")
    @classmethod
    def validate_entity_type(cls, value: Any) -> str:
        token = normalize_memory_token(value)
        if not token:
            raise ValueError("entity_type cannot be empty")
        return token[:80]

    @field_validator("relation", mode="before")
    @classmethod
    def validate_relation(cls, value: Any) -> str:
        token = normalize_memory_token(value)
        if not token:
            raise ValueError("relation cannot be empty")
        return token[:80]

    @field_validator("attributes", mode="before")
    @classmethod
    def normalize_attributes(cls, value: Any) -> dict[str, str]:
        if not isinstance(value, dict):
            return {}
        normalized: dict[str, str] = {}
        for key, item in value.items():
            name = normalize_memory_token(key)
            text = normalize_memory_value(item)
            if name and text:
                normalized[name] = text[:120]
        return normalized


class MemoryEvent(BaseModel):
    """Application-owned memory event contract shared by memory providers."""

    id: UUID | None = None
    type: str = Field(
        description=(
            "Memory type: preference, feedback, reading_state, entity, "
            "correction, or forget."
        )
    )
    subject: str = Field(
        description=(
            "Memory subject: user, book, author, tag, theme, style, genre, mood, "
            "pacing, content, pet, person, object, or entity."
        )
    )
    value: str = Field(description="Concise memory value in natural language.")
    polarity: str = Field(
        default="neutral",
        description="like, dislike, neutral, want, read, or avoid.",
    )
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    user_id: UUID
    thread_id: UUID | None = None
    source: str = Field(default="chat_turn", description="chat_turn, tool, or manual.")
    metadata: dict[str, Any] = Field(default_factory=dict)
    state_category: str | None = Field(
        default=None,
        description="User-state category: profile, preference, relation, feedback, or short_term.",
    )
    state_key: str = Field(
        default="",
        description="Stable open-vocabulary key used to retrieve or compare this user state.",
    )
    state_status: str = Field(
        default="active",
        description="Processing status for this user-state record.",
    )
    raw_text: str = Field(
        default="",
        description="Exact user-authored text retained as the authoritative source.",
    )
    state_value: dict[str, Any] = Field(default_factory=dict)
    relation: dict[str, Any] = Field(default_factory=dict)
    use_when: list[str] = Field(default_factory=list)
    valid_until: datetime | None = None
    confirmation_question: str = ""
    revision_of: UUID | None = None
    superseded_by: UUID | None = None
    forgotten: bool = Field(
        default=False,
        validation_alias=AliasChoices("forgotten", "is_deleted"),
        description="Whether this memory has been forgotten and is no longer active.",
    )
    created_at: datetime | None = None
    updated_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    @field_validator("type", mode="before")
    @classmethod
    def validate_type(cls, value: Any) -> str:
        return validate_memory_token("type", value, MEMORY_TYPES)

    @field_validator("subject", mode="before")
    @classmethod
    def validate_subject(cls, value: Any) -> str:
        return validate_memory_token("subject", value, MEMORY_SUBJECTS)

    @field_validator("polarity", mode="before")
    @classmethod
    def validate_polarity(cls, value: Any) -> str:
        return validate_memory_token("polarity", value, MEMORY_POLARITIES)

    @field_validator("source", mode="before")
    @classmethod
    def validate_source(cls, value: Any) -> str:
        return validate_memory_token("source", value, MEMORY_SOURCES)

    @field_validator("state_category", mode="before")
    @classmethod
    def validate_state_category(cls, value: Any) -> str | None:
        token = normalize_memory_token(value)
        if not token:
            return None
        return validate_memory_token("state_category", token, USER_STATE_CATEGORIES)

    @field_validator("state_status", mode="before")
    @classmethod
    def validate_state_status(cls, value: Any) -> str:
        return validate_memory_token("state_status", value, USER_STATE_STATUSES)

    @field_validator("state_key", "raw_text", "confirmation_question", mode="before")
    @classmethod
    def clean_user_state_text(cls, value: Any) -> str:
        return normalize_memory_value(value)

    @field_validator("use_when", mode="before")
    @classmethod
    def clean_use_when(cls, value: Any) -> list[str]:
        if not isinstance(value, list):
            return []
        result: list[str] = []
        for item in value:
            text = normalize_memory_value(item)
            if text and text not in result:
                result.append(text[:120])
        return result[:12]

    @field_validator("value", mode="before")
    @classmethod
    def clean_value(cls, value: Any) -> str:
        text = normalize_memory_value(value)
        if not text:
            raise ValueError("value cannot be empty")
        return text


def memory_source_for_candidate_source_kind(source_kind: str) -> str:
    """Map granular candidate provenance into the existing MemoryEvent source enum."""
    token = validate_memory_token(
        "source_kind",
        source_kind,
        MEMORY_CANDIDATE_SOURCE_KINDS,
    )
    if token == "manual":
        return "manual"
    if token == "user_message":
        return "chat_turn"
    return "tool"


class MemoryCandidate(BaseModel):
    """Candidate long-term memory proposed by an agent, tool, API, or provider."""

    type: str = Field(description="Memory type proposed for persistence.")
    subject: str = Field(description="Memory subject proposed for persistence.")
    value: str = Field(description="Concise memory value proposed for persistence.")
    polarity: str = Field(default="neutral")
    scope: str = Field(default="long_term_memory")
    source_text: str = Field(
        default="",
        description="The user text or operation text that produced the candidate.",
    )
    source_kind: str = Field(default="user_message")
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    user_id: UUID
    thread_id: UUID | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("type", mode="before")
    @classmethod
    def validate_type(cls, value: Any) -> str:
        return validate_memory_token("type", value, MEMORY_TYPES)

    @field_validator("subject", mode="before")
    @classmethod
    def validate_subject(cls, value: Any) -> str:
        return validate_memory_token("subject", value, MEMORY_SUBJECTS)

    @field_validator("polarity", mode="before")
    @classmethod
    def validate_polarity(cls, value: Any) -> str:
        return validate_memory_token("polarity", value, MEMORY_POLARITIES)

    @field_validator("scope", mode="before")
    @classmethod
    def validate_scope(cls, value: Any) -> str:
        return validate_memory_token("scope", value, INFORMATION_SCOPES)

    @field_validator("source_kind", mode="before")
    @classmethod
    def validate_source_kind(cls, value: Any) -> str:
        return validate_memory_token(
            "source_kind",
            value,
            MEMORY_CANDIDATE_SOURCE_KINDS,
        )

    @field_validator("value", mode="before")
    @classmethod
    def clean_value(cls, value: Any) -> str:
        text = normalize_memory_value(value)
        if not text:
            raise ValueError("value cannot be empty")
        return text

    @field_validator("source_text", mode="before")
    @classmethod
    def clean_source_text(cls, value: Any) -> str:
        return normalize_memory_value(value)

    def to_memory_event(self) -> MemoryEvent:
        metadata = dict(self.metadata)
        admission_metadata = dict(metadata.get("admission") or {})
        admission_metadata.update(
            {
                "scope": self.scope,
                "source_kind": self.source_kind,
                "source_text": self.source_text,
            }
        )
        metadata["admission"] = admission_metadata
        return MemoryEvent(
            user_id=self.user_id,
            thread_id=self.thread_id,
            type=self.type,
            subject=self.subject,
            value=self.value,
            polarity=self.polarity,
            confidence=self.confidence,
            source=memory_source_for_candidate_source_kind(self.source_kind),
            metadata=metadata,
        )


class MemoryAdmissionDecision(BaseModel):
    """Decision returned before a candidate can become long-term memory."""

    decision: str
    reason: str = ""
    candidate: MemoryCandidate
    target_memory_id: UUID | None = None
    warnings: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("decision", mode="before")
    @classmethod
    def validate_decision(cls, value: Any) -> str:
        return validate_memory_token(
            "decision",
            value,
            MEMORY_ADMISSION_DECISIONS,
        )

    @property
    def allowed(self) -> bool:
        return self.decision == "allow"


class MemoryConflict(BaseModel):
    """Structured relation between a new candidate and one current memory."""

    conflict_type: str
    existing_memory_id: UUID | None = None
    candidate: MemoryCandidate
    severity: str = "medium"
    suggested_decision: str
    reason: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("conflict_type", mode="before")
    @classmethod
    def validate_conflict_type(cls, value: Any) -> str:
        return validate_memory_token(
            "conflict_type",
            value,
            MEMORY_CONFLICT_TYPES,
        )

    @field_validator("severity", mode="before")
    @classmethod
    def validate_severity(cls, value: Any) -> str:
        return validate_memory_token(
            "severity",
            value,
            MEMORY_CONFLICT_SEVERITIES,
        )

    @field_validator("suggested_decision", mode="before")
    @classmethod
    def validate_suggested_decision(cls, value: Any) -> str:
        return validate_memory_token(
            "suggested_decision",
            value,
            MEMORY_CONFLICT_DECISIONS,
        )


class MemoryConflictResolution(BaseModel):
    """Resolver decision after comparing a candidate with current memories."""

    decision: str = "allow"
    reason: str = ""
    candidate: MemoryCandidate
    target_memory_id: UUID | None = None
    conflicts: list[MemoryConflict] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("decision", mode="before")
    @classmethod
    def validate_decision(cls, value: Any) -> str:
        return validate_memory_token(
            "decision",
            value,
            MEMORY_CONFLICT_DECISIONS,
        )


class MemoryAdmissionResult(BaseModel):
    """Result of admission plus optional committed memory event."""

    decision: MemoryAdmissionDecision
    memory: MemoryEvent | None = None
    conflicts: list[MemoryConflict] = Field(default_factory=list)
    provider_sources: list[str] = Field(default_factory=list)


class MemorySearchResult(BaseModel):
    """Aggregated memory search result returned to agents."""

    profile_summary: str = ""
    preferred_tags: list[str] = Field(default_factory=list)
    disliked_tags: list[str] = Field(default_factory=list)
    favorite_authors: list[str] = Field(default_factory=list)
    disliked_authors: list[str] = Field(default_factory=list)
    reading_states: list[dict[str, Any]] = Field(default_factory=list)
    relevant_events: list[MemoryEvent] = Field(default_factory=list)
    provider_sources: list[str] = Field(default_factory=list)
    provider_telemetry: list[dict[str, Any]] = Field(default_factory=list)


class MemoryRecallProviderRequest(BaseModel):
    """Input envelope for long-term memory recall enhancers such as mem0."""

    user_id: UUID
    thread_id: UUID | None = None
    query: str = ""
    limit: int = Field(default=10, ge=1, le=50)
    filters: dict[str, Any] = Field(default_factory=dict)
    current_memories: list[MemoryEvent] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("query", mode="before")
    @classmethod
    def clean_query(cls, value: Any) -> str:
        return normalize_memory_value(value)


class MemoryRecallProviderResult(BaseModel):
    """Provider output envelope for app-owned memory recall."""

    provider_name: str
    status: str
    memories: list[MemoryEvent] = Field(default_factory=list)
    error: str | None = None
    duration_ms: int = Field(default=0, ge=0)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("provider_name", mode="before")
    @classmethod
    def clean_provider_name(cls, value: Any) -> str:
        text = normalize_memory_value(value)
        if not text:
            raise ValueError("provider_name cannot be empty")
        return text

    @field_validator("status", mode="before")
    @classmethod
    def validate_status(cls, value: Any) -> str:
        return map_memory_provider_status(value)

    @field_validator("error", mode="before")
    @classmethod
    def clean_error(cls, value: Any) -> str | None:
        text = normalize_memory_value(value)
        return text or None

    @field_validator("memories", mode="after")
    @classmethod
    def validate_memory_metadata(
        cls,
        value: list[MemoryEvent],
    ) -> list[MemoryEvent]:
        for memory in value:
            if not memory.metadata.get("provider_source"):
                raise ValueError("memory metadata.provider_source is required")
            if memory.metadata.get("provider_raw") is None:
                raise ValueError("memory metadata.provider_raw is required")
        return value


class CurrentMemoryListResult(BaseModel):
    """Current active memories shown in the default user-facing memory view."""

    user_id: UUID
    memories: list[MemoryEvent] = Field(default_factory=list)
    total: int = 0
    limit: int = 50
    offset: int = 0
    provider_sources: list[str] = Field(default_factory=list)


class MemoryEventListResult(BaseModel):
    """Paginated audit event list for advanced memory history."""

    user_id: UUID
    events: list[MemoryEvent] = Field(default_factory=list)
    total: int = 0
    limit: int = 50
    offset: int = 0
    include_forgotten: bool = False
    include_superseded: bool = False
    include_audit: bool = False
    provider_sources: list[str] = Field(default_factory=list)


class MemoryForgetResult(BaseModel):
    """Result for a forget operation."""

    user_id: UUID
    forgotten_count: int
    forgotten_event_ids: list[UUID] = Field(default_factory=list)
    provider_sources: list[str] = Field(default_factory=list)
