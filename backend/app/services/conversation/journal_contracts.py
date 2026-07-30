from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal
from uuid import UUID, uuid5

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)


ConversationRole = Literal["user", "assistant", "system"]
ConversationEventType = Literal[
    "user_message",
    "assistant_published",
    "clarification_requested",
    "turn_failed",
]
LEGACY_SHADOW_ENROLLMENT_SCHEMA_VERSION = "agent-shadow-enrollment-v1"
SHADOW_ENROLLMENT_SCHEMA_VERSION = "agent-shadow-enrollment-v2"
_FORBIDDEN_METADATA_FIELDS = frozenset(
    {
        "access_token",
        "api_key",
        "authorization",
        "credentials",
        "password",
        "refresh_token",
        "request_id",
        "secret",
        "secret_key",
        "thread_id",
        "user_id",
    }
)


class JournalModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class LegacyConversationShadowEnrollment(JournalModel):
    """Read-only compatibility contract for historical v1 enrollments."""

    schema_version: Literal["agent-shadow-enrollment-v1"] = (
        LEGACY_SHADOW_ENROLLMENT_SCHEMA_VERSION
    )
    controller_fingerprint: str = Field(pattern="^[0-9a-f]{64}$")
    prompt_version: str = Field(min_length=1, max_length=64)
    model_id: UUID
    model_name: str = Field(min_length=1, max_length=256)
    timezone: str = Field(min_length=1, max_length=64)


class ConversationShadowEnrollment(JournalModel):
    """Current durable eligibility stamp for one Shadow dry-run."""

    schema_version: Literal["agent-shadow-enrollment-v2"] = (
        SHADOW_ENROLLMENT_SCHEMA_VERSION
    )
    source_commit_sha: str = Field(pattern="^[0-9a-f]{40}$")
    controller_fingerprint: str = Field(pattern="^[0-9a-f]{64}$")
    prompt_version: str = Field(min_length=1, max_length=64)
    model_id: UUID
    model_name: str = Field(min_length=1, max_length=256)
    timezone: str = Field(min_length=1, max_length=64)


StoredConversationShadowEnrollment = Annotated[
    LegacyConversationShadowEnrollment | ConversationShadowEnrollment,
    Field(discriminator="schema_version"),
]


class AppendConversationEvent(JournalModel):
    """System-owned input for one immutable journal append."""

    user_id: UUID
    thread_id: UUID
    request_id: str = Field(min_length=1, max_length=128)
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1)
    receipt_refs: list[str] = Field(default_factory=list, max_length=64)
    metadata: dict[str, Any] = Field(default_factory=dict)
    shadow_enrollment: ConversationShadowEnrollment | None = None

    @field_validator("metadata")
    @classmethod
    def reject_unsafe_metadata(
        cls,
        value: dict[str, Any],
    ) -> dict[str, Any]:
        invalid = sorted(_forbidden_metadata_paths(value))
        if invalid:
            raise ValueError(
                "conversation metadata contains forbidden fields: "
                + ", ".join(invalid)
            )
        return value

    @model_validator(mode="after")
    def validate_receipt_ownership(self) -> "AppendConversationEvent":
        if self.role == "user" and self.receipt_refs:
            raise ValueError("user conversation events cannot cite receipts")
        if self.role != "user" and self.shadow_enrollment is not None:
            raise ValueError(
                "only user conversation events can carry Shadow enrollment"
            )
        return self

    @property
    def event_type(self) -> ConversationEventType:
        return (
            "user_message"
            if self.role == "user"
            else "assistant_published"
        )

    @property
    def exchange_id(self) -> UUID:
        return uuid5(self.thread_id, f"conversation-request:{self.request_id}")


class AppendConversationLifecycleEvent(JournalModel):
    """System-owned lifecycle event used to rebuild working state."""

    user_id: UUID
    thread_id: UUID
    request_id: str = Field(min_length=1, max_length=128)
    event_type: Literal["clarification_requested", "turn_failed"]
    role: Literal["assistant", "system"]
    content: str = Field(min_length=1, max_length=4_000)
    receipt_refs: list[str] = Field(default_factory=list, max_length=64)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("metadata")
    @classmethod
    def reject_unsafe_metadata(
        cls,
        value: dict[str, Any],
    ) -> dict[str, Any]:
        invalid = sorted(_forbidden_metadata_paths(value))
        if invalid:
            raise ValueError(
                "conversation metadata contains forbidden fields: "
                + ", ".join(invalid)
            )
        return value

    @model_validator(mode="after")
    def validate_type_role_pair(self) -> "AppendConversationLifecycleEvent":
        expected = (
            "assistant"
            if self.event_type == "clarification_requested"
            else "system"
        )
        if self.role != expected:
            raise ValueError("conversation lifecycle event role mismatch")
        if self.event_type == "turn_failed" and self.receipt_refs:
            raise ValueError("failed turns cannot claim completed receipts")
        return self

    @property
    def exchange_id(self) -> UUID:
        return uuid5(self.thread_id, f"conversation-request:{self.request_id}")


class ConversationJournalEvent(JournalModel):
    id: UUID
    user_id: UUID
    thread_id: UUID
    request_id: str
    exchange_id: UUID
    sequence_no: int = Field(ge=1)
    event_type: ConversationEventType
    role: ConversationRole
    content: str
    receipt_refs: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    shadow_enrollment: StoredConversationShadowEnrollment | None = None
    created_at: datetime

    @model_validator(mode="after")
    def validate_type_role_pair(self) -> "ConversationJournalEvent":
        expected = {
            "user_message": "user",
            "assistant_published": "assistant",
            "clarification_requested": "assistant",
            "turn_failed": "system",
        }[self.event_type]
        if self.role != expected:
            raise ValueError("conversation event type and role do not match")
        if self.role == "user" and self.receipt_refs:
            raise ValueError("user conversation events cannot cite receipts")
        if self.event_type == "turn_failed" and self.receipt_refs:
            raise ValueError("failed turns cannot cite completed receipts")
        if self.role != "user" and self.shadow_enrollment is not None:
            raise ValueError(
                "only user conversation events can carry Shadow enrollment"
            )
        return self


class ConversationJournalPage(JournalModel):
    events: list[ConversationJournalEvent] = Field(default_factory=list)
    has_more: bool = False


def _forbidden_metadata_paths(
    value: Any,
    *,
    path: str = "metadata",
) -> set[str]:
    found: set[str] = set()
    if isinstance(value, dict):
        for key, child in value.items():
            key_text = str(key)
            child_path = f"{path}.{key_text}"
            if key_text.lower() in _FORBIDDEN_METADATA_FIELDS:
                found.add(child_path)
            found.update(
                _forbidden_metadata_paths(child, path=child_path)
            )
    elif isinstance(value, (list, tuple)):
        for index, child in enumerate(value):
            found.update(
                _forbidden_metadata_paths(
                    child,
                    path=f"{path}[{index}]",
                )
            )
    return found
