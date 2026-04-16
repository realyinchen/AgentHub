from sqlalchemy import Column, BigInteger, Integer, String, Text, DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import UUID, JSONB
from datetime import datetime, timezone

from app.database.base import Base


def utc_now():
    return datetime.now(timezone.utc)


class MessageStepRecord(Base):
    """Model for storing agent execution steps (human, ai, tool)."""
    __tablename__ = "message_steps"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    thread_id = Column(
        UUID(as_uuid=True),
        ForeignKey("conversations.thread_id", ondelete="CASCADE"),
        nullable=False,
    )
    step_number = Column(Integer, nullable=False)
    message_type = Column(String(16), nullable=False)  # 'human', 'ai', 'tool'

    # Tool fields
    tool_name = Column(String(128), nullable=True)
    tool_args = Column(JSONB, nullable=True)
    tool_output = Column(Text, nullable=True)
    tool_call_id = Column(String(128), nullable=True)  # For matching tool call with result

    # AI response fields
    content = Column(Text, nullable=True)
    thinking = Column(Text, nullable=True)
    tool_calls = Column(JSONB, nullable=True)  # Tool calls from AI message

    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
