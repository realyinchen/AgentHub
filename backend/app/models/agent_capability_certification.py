import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.infra.database.base import Base
from app.models.base import utc_now


class AgentCapabilityCertification(Base):
    """Immutable result of one full Agent capability certification run."""

    __tablename__ = "agent_capability_certifications"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    model_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("models.id", ondelete="CASCADE"),
        nullable=False,
    )
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    provider_model_id: Mapped[str] = mapped_column(String(256), nullable=False)
    configuration_fingerprint: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
    )
    contract_version: Mapped[str] = mapped_column(String(64), nullable=False)
    controller_fingerprint: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
    )
    source_commit_sha: Mapped[str | None] = mapped_column(
        String(40),
        nullable=True,
    )
    certified: Mapped[bool] = mapped_column(Boolean, nullable=False)
    checked_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
    )
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    cases: Mapped[list[dict]] = mapped_column(JSONB, nullable=False, default=list)
    failure_cases: Mapped[list[str]] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
    )
    error_type: Mapped[str | None] = mapped_column(String(128), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
