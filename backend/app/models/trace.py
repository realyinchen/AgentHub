"""Trace execution model — persisted DAG snapshots.

Each row stores the complete ExecutionDag for a single request_id
(user→agent turn), built at write time so trace endpoints never
depend on graph compilation or agent liveness.
"""

from uuid import UUID, uuid4
from datetime import datetime, timezone

from sqlalchemy import BigInteger, JSON, String, DateTime, Integer, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.infra.database import Base


def utc_now():
    return datetime.now(timezone.utc)


class TraceExecution(Base):
    __tablename__ = "trace_executions"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    thread_id: Mapped[UUID] = mapped_column(Uuid, nullable=False, index=True)
    agent_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    request_id: Mapped[str] = mapped_column(
        String(128), nullable=False, index=True
    )
    dag_data: Mapped[dict] = mapped_column(
        JSON, nullable=False, comment="Complete ExecutionDag as JSON"
    )
    model_name: Mapped[str | None] = mapped_column(
        String(128), nullable=True, comment="LLM model used for this turn"
    )
    total_steps: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, comment="Number of steps in this turn"
    )
    # Per-request token usage
    input_tokens: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0
    )
    cache_read: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0
    )
    output_tokens: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0
    )
    reasoning: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0
    )
    total_tokens: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
