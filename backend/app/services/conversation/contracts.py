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
