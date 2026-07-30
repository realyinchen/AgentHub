import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.infra.database.base import Base
from app.models.base import utc_now


class AgentShadowObservationRecord(Base):
    """Immutable, de-identified telemetry for one Shadow decision."""

    __tablename__ = "agent_shadow_observations"
    __table_args__ = (
        CheckConstraint(
            "controller_status IN "
            "('denied', 'shadow_valid', 'shadow_invalid', 'failed')",
            name="ck_agent_shadow_observation_status",
        ),
        CheckConstraint(
            "latency_ms >= 0 AND side_effect_count >= 0",
            name="ck_agent_shadow_observation_counts",
        ),
        CheckConstraint(
            "journal_sequence_watermark > 0",
            name="ck_agent_shadow_observation_watermark",
        ),
        UniqueConstraint(
            "observation_key",
            name="uq_agent_shadow_observation_key",
        ),
        Index(
            "idx_agent_shadow_observation_window",
            "controller_fingerprint",
            "created_at",
        ),
        Index(
            "idx_agent_shadow_observation_request",
            "thread_id",
            "request_id",
        ),
        Index(
            "idx_agent_shadow_observation_watermark",
            "thread_id",
            "journal_sequence_watermark",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        primary_key=True,
        default=uuid.uuid4,
    )
    observation_key: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
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
    request_id: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
    )
    journal_sequence_watermark: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )
    model_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        ForeignKey("models.id", ondelete="SET NULL"),
        nullable=True,
    )
    certification_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        ForeignKey(
            "agent_capability_certifications.id",
            ondelete="SET NULL",
        ),
        nullable=True,
    )
    configuration_fingerprint: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
    )
    source_commit_sha: Mapped[str | None] = mapped_column(
        String(40),
        nullable=True,
    )
    controller_fingerprint: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
    )
    agent_core_contract_version: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
    )
    certification_contract_version: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
    )
    prompt_version: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
    )
    context_snapshot_hash: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
    )
    input_evidence_hash: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
    )
    controller_status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
    )
    output_mode: Mapped[str | None] = mapped_column(
        String(32),
        nullable=True,
    )
    valid: Mapped[bool | None] = mapped_column(
        Boolean,
        nullable=True,
    )
    would_execute: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
    )
    side_effect_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
    )
    latency_ms: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )
    proposal_summary: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
    )
    plan_summary: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
    )
    checks: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
    )
    violation_codes: Mapped[list[str]] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
    )
    error_hashes: Mapped[list[str]] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
    )
