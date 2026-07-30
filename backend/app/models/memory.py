import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    Uuid,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.infra.database.base import Base
from app.models.base import utc_now


class MemoryEventRecord(Base):
    """Event-sourced user memory owned by the application contract."""

    __tablename__ = "memory_events"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    thread_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("conversations.thread_id", ondelete="SET NULL"), nullable=True
    )
    type: Mapped[str] = mapped_column(String(32), nullable=False)
    subject: Mapped[str] = mapped_column(String(64), nullable=False)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    polarity: Mapped[str] = mapped_column(String(32), nullable=False, default="neutral")
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    source: Mapped[str] = mapped_column(String(32), nullable=False, default="chat_turn")
    metadata_json: Mapped[dict] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict
    )
    revision_of: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("memory_events.id", ondelete="SET NULL"), nullable=True
    )
    superseded_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("memory_events.id", ondelete="SET NULL"), nullable=True
    )
    chain_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    schema_key: Mapped[str | None] = mapped_column(String(128), nullable=True)
    memory_key: Mapped[str | None] = mapped_column(String(256), nullable=True)
    version_no: Mapped[int | None] = mapped_column(Integer, nullable=True)
    operation: Mapped[str | None] = mapped_column(String(16), nullable=True)
    previous_version_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        ForeignKey("memory_events.id", ondelete="SET NULL"),
        nullable=True,
    )
    source_event_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        ForeignKey("conversation_events.id", ondelete="SET NULL"),
        nullable=True,
    )
    receipt_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    canonical_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    schema_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    valid_from: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    valid_to: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    is_deleted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        onupdate=utc_now,
    )
