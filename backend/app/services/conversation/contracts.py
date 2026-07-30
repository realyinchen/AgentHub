from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ConversationModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ConversationTurn(ConversationModel):
    """Identity-free ordered conversation evidence."""

    role: Literal["user", "assistant"]
    turn_offset: int = Field(le=-1)
    content: str = Field(min_length=1, max_length=4000)

    @field_validator("content", mode="before")
    @classmethod
    def normalize_content(cls, value: object) -> str:
        return " ".join(str(value or "").split()).strip()


class ConversationWindow(ConversationModel):
    """Recent committed chat messages; never a long-term-memory projection."""

    turns: list[ConversationTurn] = Field(default_factory=list, max_length=16)

    @property
    def user_turns(self) -> list[ConversationTurn]:
        return [turn for turn in self.turns if turn.role == "user"]


class ConversationRecallResult(ConversationModel):
    result_mode: Literal["conversation_recall"] = "conversation_recall"
    status: Literal["completed", "empty"] = "completed"
    turns: list[ConversationTurn] = Field(default_factory=list)
    answer: str = ""


class ConversationReadRequest(ConversationModel):
    """Business-only selection for exact recent-conversation reading."""

    target: Literal["user", "assistant", "exchange"] = "exchange"
    selection: Literal["latest", "last_n"] = "latest"
    count: int = Field(default=1, ge=1, le=8)


class ConversationExchange(ConversationModel):
    """One user message paired only with its published assistant response."""

    user: ConversationTurn
    assistant: ConversationTurn | None = None
    status: Literal["completed", "incomplete"] = "completed"


class ConversationReadResult(ConversationModel):
    result_mode: Literal["conversation_read"] = "conversation_read"
    status: Literal["completed", "empty"] = "completed"
    target: Literal["user", "assistant", "exchange"] = "exchange"
    exchanges: list[ConversationExchange] = Field(default_factory=list)
    turns: list[ConversationTurn] = Field(default_factory=list)
    answer: str = ""
