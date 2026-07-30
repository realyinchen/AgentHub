import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.infra.database.base import Base
from app.models.base import utc_now


class ConversationEventRecord(Base):
    """Immutable, app-owned record of a published conversation event."""

    __tablename__ = "conversation_events"
    __table_args__ = (
        CheckConstraint(
            "event_type IN ('user_message', 'assistant_published', "
            "'clarification_requested', 'turn_failed')",
            name="ck_conversation_events_type",
        ),
        CheckConstraint(
            "role IN ('user', 'assistant', 'system')",
            name="ck_conversation_events_role",
        ),
        CheckConstraint(
            "(event_type = 'user_message' AND role = 'user') OR "
            "(event_type IN ('assistant_published', 'clarification_requested') "
            "AND role = 'assistant') OR "
            "(event_type = 'turn_failed' AND role = 'system')",
            name="ck_conversation_events_type_role",
        ),
        CheckConstraint(
            "sequence_no > 0",
            name="ck_conversation_events_sequence_positive",
        ),
        UniqueConstraint(
            "thread_id",
            "sequence_no",
            name="uq_conversation_events_thread_sequence",
        ),
        UniqueConstraint(
            "thread_id",
            "request_id",
            "event_type",
            name="uq_conversation_events_request_type",
        ),
        Index(
            "uq_conversation_events_request_terminal",
            "thread_id",
            "request_id",
            unique=True,
            postgresql_where=text(
                "event_type IN "
                "('assistant_published', 'clarification_requested', 'turn_failed')"
            ),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        primary_key=True,
        default=uuid.uuid4,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    thread_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("conversations.thread_id", ondelete="CASCADE"),
        nullable=False,
    )
    request_id: Mapped[str] = mapped_column(String(128), nullable=False)
    exchange_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    sequence_no: Mapped[int] = mapped_column(BigInteger, nullable=False)
    event_type: Mapped[str] = mapped_column(String(32), nullable=False)
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    receipt_refs: Mapped[list[str]] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
    )
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        "metadata",
        JSONB,
        nullable=False,
        default=dict,
    )
    shadow_enrollment_json: Mapped[dict[str, Any] | None] = mapped_column(
        "shadow_enrollment",
        JSONB(none_as_null=True),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
    )
