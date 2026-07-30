from uuid import UUID, uuid4
from datetime import datetime

from sqlalchemy import Boolean, String, DateTime, BigInteger, Uuid, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from app.infra.database import Base
from app.models.base import utc_now


class Conversation(Base):
    __tablename__ = "conversations"

    thread_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    title: Mapped[str] = mapped_column(String(64), nullable=False)
    is_deleted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        onupdate=utc_now,
    )

    # Token usage fields (cumulative for the conversation)
    input_tokens: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    output_tokens: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    total_tokens: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    journal_sequence: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        default=0,
    )
