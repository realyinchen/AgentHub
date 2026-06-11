import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.infra.database.base import Base
from app.models.base import utc_now


class ModelCapabilityCheck(Base):
    """Observed runtime capability check for a configured model."""

    __tablename__ = "model_capability_checks"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    model_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("models.id", ondelete="CASCADE"), nullable=False
    )
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    provider_model_id: Mapped[str] = mapped_column(String(256), nullable=False)
    checked_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    chat_ok: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    thinking_request_ok: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    reasoning_text_ok: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    streaming_reasoning_ok: Mapped[bool | None] = mapped_column(
        Boolean, nullable=True
    )
    reasoning_field_path: Mapped[str | None] = mapped_column(
        String(128), nullable=True
    )
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_summary: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
