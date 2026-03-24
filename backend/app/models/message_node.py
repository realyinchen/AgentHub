from sqlalchemy import Column, String, DateTime, Integer, ForeignKey, Text
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship
from uuid import uuid4
from datetime import datetime, timezone

from app.database.base import Base


def utc_now():
    return datetime.now(timezone.utc)


class MessageNode(Base):
    """Message node for tree-structured conversation history."""
    __tablename__ = "message_nodes"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    thread_id = Column(
        UUID(as_uuid=True),
        ForeignKey("conversations.thread_id", ondelete="CASCADE"),
        nullable=False,
    )
    role = Column(String(16), nullable=False)  # 'user' or 'assistant'
    content = Column(Text, nullable=False)
    parent_id = Column(
        UUID(as_uuid=True),
        ForeignKey("message_nodes.id", ondelete="SET NULL"),
        nullable=True,
    )
    branch_index = Column(Integer, nullable=False, default=0)
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
    )
    tool_calls = Column(JSONB, nullable=True)
    tool_call_status = Column(String(16), nullable=True)  # 'pending', 'completed', 'failed'
    custom_data = Column(JSONB, nullable=True)

    # Relationships
    children = relationship(
        "MessageNode",
        backref="parent",
        remote_side=[id],
        foreign_keys=[parent_id],
        lazy="select",
    )