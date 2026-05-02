import json
from typing import Any, Literal
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    Integer,
    String,
    Text,
    DateTime,
    ForeignKey,
    UniqueConstraint,
    Uuid,
    JSON,
    Index,
    TypeDecorator,
)
from sqlalchemy.orm import Mapped, mapped_column
from datetime import datetime, timezone

from app.database.base import Base


class UnicodeJSON(TypeDecorator):
    """Custom JSON type that preserves Unicode characters (doesn't escape to \\uXXXX)."""
    
    impl = JSON
    cache_ok = True
    
    def process_bind_param(self, value, dialect):
        if value is not None:
            # The JSON impl will handle the serialization
            return value
        return value
    
    def process_result_value(self, value, dialect):
        return value


def utc_now():
    return datetime.now(timezone.utc)


class MessageStepRecord(Base):
    """Model for storing agent execution steps (human, ai, tool)."""

    __tablename__ = "message_steps"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    thread_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("conversations.thread_id", ondelete="CASCADE"),
        nullable=False,
    )
    session_id: Mapped[UUID] = mapped_column(
        Uuid, nullable=False
    )  # Groups steps by conversation turn
    step_number: Mapped[int] = mapped_column(Integer, nullable=False)
    message_type: Mapped[Literal["human", "ai", "tool"]] = mapped_column(
        String(16), nullable=False
    )

    # Tool fields
    tool_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    tool_args: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    tool_output: Mapped[str | None] = mapped_column(Text, nullable=True)
    tool_call_id: Mapped[str | None] = mapped_column(
        String(128), nullable=True
    )  # For matching tool call with result

    # AI response fields
    content: Mapped[str | None] = mapped_column(Text, nullable=True)
    thinking: Mapped[str | None] = mapped_column(Text, nullable=True)
    tool_calls: Mapped[list[Any] | None] = mapped_column(
        JSON, nullable=True
    )  # Tool calls from AI message (stored with Unicode preserved)

    # Trace fields (for Agent Trace Kanban Viewer)
    run_id: Mapped[str | None] = mapped_column(
        String(128), nullable=True
    )  # LangGraph run_id
    parent_run_id: Mapped[str | None] = mapped_column(
        String(128), nullable=True
    )  # Parent run_id (for subagent)
    latency_ms: Mapped[int | None] = mapped_column(
        Integer, nullable=True
    )  # Step latency in milliseconds
    model_name: Mapped[str | None] = mapped_column(
        String(128), nullable=True
    )  # LLM model name used

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )

    __table_args__ = (
        UniqueConstraint(
            "thread_id", "session_id", "step_number", name="unique_thread_session_step"
        ),
        # Indexes for trace API performance
        Index("ix_message_steps_thread_id", "thread_id"),
        Index("ix_message_steps_session_id", "session_id"),
        Index("ix_message_steps_created_at", "created_at"),
    )
