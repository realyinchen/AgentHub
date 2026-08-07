from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)


CanonicalizationStatus = Literal[
    "ready",
    "clarification_required",
    "rejected",
]
MemoryMutationStatus = Literal[
    "created",
    "revised",
    "noop_duplicate",
    "forgotten",
]
MemorySearchScope = Literal["current", "previous", "earliest", "timeline"]


class VersionedMemoryModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class MemoryAssertionProposal(VersionedMemoryModel):
    """Model-visible semantic assertion; all storage identity is absent."""

    subject: str = Field(min_length=1, max_length=256)
    predicate: str = Field(min_length=1, max_length=256)
    value: dict[str, Any] = Field(default_factory=dict)
    qualifiers: dict[str, Any] = Field(default_factory=dict)
    evidence_quote: str = Field(min_length=1, max_length=4000)

    @field_validator(
        "subject",
        "predicate",
        "evidence_quote",
        mode="before",
    )
    @classmethod
    def normalize_text(cls, value: Any) -> str:
        return " ".join(str(value or "").split()).strip()


class RememberMemoryRequest(VersionedMemoryModel):
    assertions: list[MemoryAssertionProposal] = Field(
        min_length=1,
        max_length=8,
    )


class SearchMemoryRequest(VersionedMemoryModel):
    query: str = Field(default="", max_length=1000)
    predicate: str = Field(default="", max_length=256)
    scope: MemorySearchScope = "current"
    depth: int = Field(default=1, ge=1, le=10)
    since: datetime | None = None
    until: datetime | None = None

    @field_validator("query", "predicate", mode="before")
    @classmethod
    def normalize_search_text(cls, value: Any) -> str:
        return " ".join(str(value or "").split()).strip()

    @model_validator(mode="after")
    def require_search_constraint(self) -> "SearchMemoryRequest":
        if not self.query and not self.predicate:
            raise ValueError(
                "memory search requires query or predicate"
            )
        if (
            self.since is not None
            and self.until is not None
            and self.since >= self.until
        ):
            raise ValueError(
                "memory timeline since must precede until"
            )
        return self


class ForgetMemoryTargetProposal(VersionedMemoryModel):
    subject: str = Field(min_length=1, max_length=256)
    predicate: str = Field(min_length=1, max_length=256)
    identity: dict[str, Any] = Field(default_factory=dict)
    qualifiers: dict[str, Any] = Field(default_factory=dict)
    evidence_quote: str = Field(min_length=1, max_length=4000)

    @field_validator(
        "subject",
        "predicate",
        "evidence_quote",
        mode="before",
    )
    @classmethod
    def normalize_target_text(cls, value: Any) -> str:
        return " ".join(str(value or "").split()).strip()


class ForgetMemoryRequest(VersionedMemoryModel):
    targets: list[ForgetMemoryTargetProposal] = Field(
        min_length=1,
        max_length=8,
    )


class CanonicalMemoryFact(VersionedMemoryModel):
    schema_key: str
    memory_key: str
    schema_version: int = Field(ge=1)
    subject: str
    predicate: str
    value: dict[str, Any]
    qualifiers: dict[str, Any] = Field(default_factory=dict)
    evidence_quote: str
    canonical_hash: str = Field(min_length=64, max_length=64)


class MemoryCanonicalizationResult(VersionedMemoryModel):
    status: CanonicalizationStatus
    facts: list[CanonicalMemoryFact] = Field(default_factory=list)
    clarification_question: str = ""
    reason_codes: list[str] = Field(default_factory=list)


class CanonicalMemoryTarget(VersionedMemoryModel):
    schema_key: str
    memory_key: str
    evidence_quote: str


class MemoryTargetResolutionResult(VersionedMemoryModel):
    status: CanonicalizationStatus
    targets: list[CanonicalMemoryTarget] = Field(default_factory=list)
    clarification_question: str = ""
    reason_codes: list[str] = Field(default_factory=list)


class MemoryVersionCommitCommand(VersionedMemoryModel):
    facts: list[CanonicalMemoryFact] = Field(min_length=1, max_length=8)
    source_event_id: UUID
    receipt_id: str = Field(min_length=1, max_length=128)


class MemoryVersionForgetCommand(VersionedMemoryModel):
    memory_keys: list[str] = Field(min_length=1, max_length=8)
    source_event_id: UUID
    receipt_id: str = Field(min_length=1, max_length=128)
    evidence_quote: str = Field(min_length=1, max_length=4000)


class MemoryVersionRecord(VersionedMemoryModel):
    id: UUID
    user_id: UUID
    thread_id: UUID | None = None
    chain_id: UUID
    schema_key: str
    memory_key: str
    version_no: int = Field(ge=1)
    operation: Literal["create", "correct", "supersede", "forget"]
    previous_version_id: UUID | None = None
    superseded_by: UUID | None = None
    source_event_id: UUID
    receipt_id: str
    canonical_hash: str
    schema_version: int = Field(ge=1)
    subject: str
    predicate: str
    value: dict[str, Any] = Field(default_factory=dict)
    qualifiers: dict[str, Any] = Field(default_factory=dict)
    evidence_quote: str
    is_tombstone: bool = False
    valid_from: datetime
    valid_to: datetime | None = None


class MemoryMutation(VersionedMemoryModel):
    memory_key: str
    status: MemoryMutationStatus
    version: MemoryVersionRecord
    previous: MemoryVersionRecord | None = None


class MemoryMutationReceipt(VersionedMemoryModel):
    result_mode: Literal["memory_mutation_receipt"] = "memory_mutation_receipt"
    receipt_id: str
    status: Literal["committed", "noop_duplicate"]
    mutations: list[MemoryMutation] = Field(default_factory=list)


class MemorySearchReceipt(VersionedMemoryModel):
    result_mode: Literal["memory_search_receipt"] = "memory_search_receipt"
    status: Literal["completed", "empty"]
    scope: MemorySearchScope = "current"
    memories: list[MemoryVersionRecord] = Field(default_factory=list)
    truncated: bool = False
