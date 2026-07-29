from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


MemoryWriteOperation = Literal["create", "correct"]
MemoryWriteDecisionStatus = Literal[
    "commit_ready",
    "clarification_required",
    "rejected",
    "noop_duplicate",
]
MemoryWriteOutcomeStatus = Literal[
    "committed",
    "clarification_required",
    "rejected",
    "noop_duplicate",
    "failed",
]
MemorySourceKind = Literal[
    "current_user_assertion",
    "prior_user_assertion",
    "quoted_user_assertion",
    "assistant_suggestion",
    "model_inference",
]


class MemoryWriteModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class MemoryClarificationContext(MemoryWriteModel):
    """Ephemeral conversation state; never a durable-memory record."""

    kind: Literal["reference", "completeness", "conflict"]
    original_utterance: str = Field(min_length=1, max_length=4000)
    target_expression: str = ""
    question: str = Field(min_length=1, max_length=1000)

    @field_validator(
        "original_utterance",
        "target_expression",
        "question",
        mode="before",
    )
    @classmethod
    def normalize_clarification_text(cls, value: Any) -> str:
        return " ".join(str(value or "").split()).strip()


class MemoryWriteRequest(MemoryWriteModel):
    """Business-only request to understand a possible durable-memory change."""

    operation: MemoryWriteOperation = "create"
    utterance: str = Field(min_length=1, max_length=4000)
    target_expression: str = ""
    explicit: bool = False
    conversation_context_required: bool = False
    semantic_fallback_allowed: bool = True
    clarification: MemoryClarificationContext | None = None

    @field_validator("utterance", "target_expression", mode="before")
    @classmethod
    def normalize_text(cls, value: Any) -> str:
        return " ".join(str(value or "").split()).strip()

    @model_validator(mode="after")
    def validate_clarification_answer(self) -> "MemoryWriteRequest":
        if self.clarification is not None and not self.explicit:
            raise ValueError("a clarification answer must remain an explicit request")
        return self


class MemorySourceEvidence(MemoryWriteModel):
    """Exact user-authored support for one proposed fact."""

    source_kind: MemorySourceKind
    turn_offset: int = Field(le=0)
    excerpt: str = Field(min_length=1, max_length=4000)

    @field_validator("excerpt", mode="before")
    @classmethod
    def normalize_excerpt(cls, value: Any) -> str:
        return " ".join(str(value or "").split()).strip()


class MemoryReferenceResolution(MemoryWriteModel):
    status: Literal["resolved", "clarification_required"]
    source: MemorySourceEvidence | None = None
    resolved_text: str = ""
    clarification_question: str = ""
    reason_codes: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_state(self) -> "MemoryReferenceResolution":
        if self.status == "resolved" and (
            self.source is None or not self.resolved_text
        ):
            raise ValueError("resolved reference requires source and resolved_text")
        if (
            self.status == "clarification_required"
            and not self.clarification_question
        ):
            raise ValueError(
                "clarification_required reference needs a question"
            )
        return self


class MemoryFactDraft(MemoryWriteModel):
    """A pre-commit fact draft; it is never a database record."""

    category: str
    state_key: str
    summary: str
    state_value: dict[str, Any] = Field(default_factory=dict)
    relation: dict[str, Any] = Field(default_factory=dict)
    use_when: list[str] = Field(default_factory=list)
    legacy_type: str
    legacy_subject: str
    legacy_value: str
    polarity: str = "neutral"
    durability: Literal["long_term", "short_term", "unknown"] = "unknown"
    source: MemorySourceEvidence
    extraction_method: Literal["deterministic", "semantic"]
    extraction_confidence: float = Field(ge=0.0, le=1.0)
    unresolved_references: list[str] = Field(default_factory=list)
    clarification_question: str = ""

    @field_validator(
        "category",
        "state_key",
        "summary",
        "legacy_type",
        "legacy_subject",
        "legacy_value",
        "polarity",
        "clarification_question",
        mode="before",
    )
    @classmethod
    def normalize_string(cls, value: Any) -> str:
        return " ".join(str(value or "").split()).strip()


class ResolvedMemoryFact(MemoryWriteModel):
    """Complete canonical fact eligible for pre-commit conflict checking."""

    category: str
    state_key: str
    summary: str
    state_value: dict[str, Any] = Field(default_factory=dict)
    relation: dict[str, Any] = Field(default_factory=dict)
    use_when: list[str] = Field(default_factory=list)
    legacy_type: str
    legacy_subject: str
    legacy_value: str
    polarity: str = "neutral"
    durability: Literal["long_term"] = "long_term"
    source: MemorySourceEvidence
    extraction_method: Literal["deterministic", "semantic"]
    extraction_confidence: float = Field(ge=0.0, le=1.0)

    @field_validator(
        "category",
        "state_key",
        "summary",
        "legacy_type",
        "legacy_subject",
        "legacy_value",
        "polarity",
        mode="before",
    )
    @classmethod
    def normalize_string(cls, value: Any) -> str:
        return " ".join(str(value or "").split()).strip()


class MemoryWriteDecision(MemoryWriteModel):
    """Fail-closed decision produced before any durable-memory write."""

    status: MemoryWriteDecisionStatus
    facts: list[ResolvedMemoryFact] = Field(default_factory=list)
    clarification_question: str = ""
    reason_codes: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_state(self) -> "MemoryWriteDecision":
        if self.status == "commit_ready" and not self.facts:
            raise ValueError("commit_ready requires at least one resolved fact")
        if self.status != "commit_ready" and self.facts:
            raise ValueError(f"{self.status} cannot carry commit-ready facts")
        if self.status == "clarification_required" and not self.clarification_question:
            raise ValueError(
                "clarification_required needs a clarification question"
            )
        return self


class MemoryCommitCommand(MemoryWriteModel):
    """The only business payload accepted by the durable-memory committer."""

    facts: list[ResolvedMemoryFact] = Field(min_length=1)
    write_mode: Literal["upsert"] = "upsert"


class MemoryWriteOutcome(MemoryWriteModel):
    result_mode: Literal["memory_write_outcome"] = "memory_write_outcome"
    status: MemoryWriteOutcomeStatus
    facts: list[ResolvedMemoryFact] = Field(default_factory=list)
    memories: list[dict[str, Any]] = Field(default_factory=list)
    clarification_question: str = ""
    pending_clarification: MemoryClarificationContext | None = None
    reason_codes: list[str] = Field(default_factory=list)
    admission: list[dict[str, Any]] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_state(self) -> "MemoryWriteOutcome":
        if self.status == "committed" and not self.memories:
            raise ValueError("committed outcome requires committed memories")
        if (
            self.status == "clarification_required"
            and not self.clarification_question
        ):
            raise ValueError(
                "clarification_required outcome needs a clarification question"
            )
        return self
