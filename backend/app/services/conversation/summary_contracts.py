from __future__ import annotations

from datetime import datetime
from typing import Literal, Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.services.conversation.journal_contracts import ConversationJournalEvent


SUMMARY_PROMPT_VERSION = "conversation-summary-v1"


class SummaryModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SummaryStatement(SummaryModel):
    text: str = Field(min_length=1, max_length=2_000)
    source_sequences: list[int] = Field(min_length=1, max_length=64)


class StructuredConversationSummary(SummaryModel):
    user_requests: list[SummaryStatement] = Field(default_factory=list)
    user_statements: list[SummaryStatement] = Field(default_factory=list)
    decisions: list[SummaryStatement] = Field(default_factory=list)
    corrections: list[SummaryStatement] = Field(default_factory=list)
    unresolved: list[SummaryStatement] = Field(default_factory=list)
    active_tasks: list[SummaryStatement] = Field(default_factory=list)
    receipt_refs: list[str] = Field(default_factory=list, max_length=128)

    @property
    def statements(self) -> list[SummaryStatement]:
        return [
            *self.user_requests,
            *self.user_statements,
            *self.decisions,
            *self.corrections,
            *self.unresolved,
            *self.active_tasks,
        ]


class ConversationSummaryDraft(SummaryModel):
    structured_content: StructuredConversationSummary
    model_id: str = Field(min_length=1, max_length=256)
    prompt_version: Literal[
        "conversation-summary-v1"
    ] = SUMMARY_PROMPT_VERSION


class ConversationSummaryCandidate(SummaryModel):
    user_id: UUID
    thread_id: UUID
    from_sequence: int = Field(ge=1)
    to_sequence: int = Field(ge=1)
    previous_summary_id: UUID | None = None
    structured_content: StructuredConversationSummary
    source_hash: str = Field(pattern="^[0-9a-f]{64}$")
    model_id: str
    prompt_version: str

    @model_validator(mode="after")
    def validate_range(self) -> "ConversationSummaryCandidate":
        if self.to_sequence < self.from_sequence:
            raise ValueError("summary sequence range is reversed")
        return self


class ConversationSummary(SummaryModel):
    id: UUID
    user_id: UUID
    thread_id: UUID
    from_sequence: int = Field(ge=1)
    to_sequence: int = Field(ge=1)
    previous_summary_id: UUID | None = None
    structured_content: StructuredConversationSummary
    source_hash: str = Field(pattern="^[0-9a-f]{64}$")
    model_id: str
    prompt_version: str
    created_at: datetime


class SummaryProvider(Protocol):
    async def summarize(
        self,
        *,
        previous: ConversationSummary | None,
        events: list[ConversationJournalEvent],
    ) -> ConversationSummaryDraft: ...


__all__ = [
    "SUMMARY_PROMPT_VERSION",
    "ConversationSummary",
    "ConversationSummaryCandidate",
    "ConversationSummaryDraft",
    "StructuredConversationSummary",
    "SummaryProvider",
    "SummaryStatement",
]
