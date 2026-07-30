import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.infra.database.base import Base
from app.models.base import utc_now


class TaskStateRecord(Base):
    __tablename__ = "task_states"
    __table_args__ = (
        UniqueConstraint(
            "thread_id",
            "origin_request_id",
            name="uq_task_state_origin_request",
        ),
    )

    task_id: Mapped[uuid.UUID] = mapped_column(
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
    origin_request_id: Mapped[str | None] = mapped_column(
        String(128),
        nullable=True,
    )
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="pending",
    )
    current_plan_version_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        ForeignKey(
            "task_plan_versions.id",
            ondelete="RESTRICT",
            use_alter=True,
            name="fk_task_state_current_plan_version",
        ),
        nullable=True,
    )
    current_action_id: Mapped[str | None] = mapped_column(
        String(128),
        nullable=True,
    )
    completed_receipt_refs: Mapped[list[str]] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
    )
    projected_receipt_refs: Mapped[list[str]] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
    )
    waiting_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    pending_clarification: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB,
        nullable=True,
    )
    recovery_cursor: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        default=0,
    )
    lease_owner: Mapped[str | None] = mapped_column(String(128), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    terminal_error: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB,
        nullable=True,
    )
    state_version: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        default=0,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        onupdate=utc_now,
    )


class TaskPlanVersionRecord(Base):
    __tablename__ = "task_plan_versions"
    __table_args__ = (
        UniqueConstraint(
            "task_id",
            "version_no",
            name="uq_task_plan_version_number",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    task_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("task_states.task_id", ondelete="CASCADE"),
        nullable=False,
    )
    version_no: Mapped[int] = mapped_column(Integer, nullable=False)
    previous_version_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        ForeignKey("task_plan_versions.id", ondelete="RESTRICT"),
        nullable=True,
    )
    plan_json: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
    )
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    origin_request_id: Mapped[str | None] = mapped_column(
        String(128),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
    )


class ActionExecutionReceiptRecord(Base):
    __tablename__ = "action_execution_receipts"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    idempotency_key: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        unique=True,
    )
    task_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        ForeignKey("task_states.task_id", ondelete="CASCADE"),
        nullable=True,
    )
    plan_version_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        ForeignKey("task_plan_versions.id", ondelete="SET NULL"),
        nullable=True,
    )
    plan_id: Mapped[str] = mapped_column(String(128), nullable=False)
    action_id: Mapped[str] = mapped_column(String(128), nullable=False)
    request_id: Mapped[str] = mapped_column(String(128), nullable=False)
    capability: Mapped[str] = mapped_column(String(128), nullable=False)
    operation: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    receipt_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
    )
