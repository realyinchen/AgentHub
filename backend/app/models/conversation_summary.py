import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    String,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.infra.database.base import Base
from app.models.base import utc_now


class ConversationSummaryRecord(Base):
    """Immutable cumulative summary derived only from ConversationJournal."""

    __tablename__ = "conversation_summaries"
    __table_args__ = (
        CheckConstraint(
            "from_sequence > 0 AND to_sequence >= from_sequence",
            name="ck_conversation_summary_range",
        ),
        UniqueConstraint(
            "thread_id",
            "to_sequence",
            "source_hash",
            "prompt_version",
            name="uq_conversation_summary_derivation",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
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
    from_sequence: Mapped[int] = mapped_column(BigInteger, nullable=False)
    to_sequence: Mapped[int] = mapped_column(BigInteger, nullable=False)
    previous_summary_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        ForeignKey("conversation_summaries.id", ondelete="RESTRICT"),
        nullable=True,
    )
    structured_content: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
    )
    source_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    model_id: Mapped[str] = mapped_column(String(256), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
    )
