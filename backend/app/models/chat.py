from sqlalchemy import Column, Boolean, String, DateTime, BigInteger
from sqlalchemy.dialects.postgresql import UUID
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
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        onupdate=utc_now,
    )
    
    # Token usage fields (cumulative for the conversation)
    input_tokens = Column(BigInteger, nullable=False, default=0)
    cache_read = Column(BigInteger, nullable=False, default=0)
    output_tokens = Column(BigInteger, nullable=False, default=0)
    reasoning = Column(BigInteger, nullable=False, default=0)
    total_tokens = Column(BigInteger, nullable=False, default=0)
