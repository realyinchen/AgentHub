from sqlalchemy import Column, Boolean, String, DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from uuid import uuid4
from datetime import datetime, timezone

from app.database.base import Base


def utc_now():
    return datetime.now(timezone.utc)


class Conversation(Base):
    __tablename__ = "conversations"

    thread_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    title = Column(String(64), nullable=False)
    agent_id = Column(String(64), nullable=True, default="chatbot")
    is_deleted = Column(Boolean, nullable=False, default=False)
    current_leaf_id = Column(
        UUID(as_uuid=True),
        ForeignKey("message_nodes.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        onupdate=utc_now,
    )

    # Relationship to current leaf node
    current_leaf = relationship(
        "MessageNode",
        foreign_keys=[current_leaf_id],
        lazy="select",
    )
