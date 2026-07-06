import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, JSON, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.infra.database.base import Base
from app.models.base import utc_now


class AppProviderConfigRecord(Base):
    """Durable app-owned provider config for memory/research integrations."""

    __tablename__ = "app_provider_configs"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    provider_key: Mapped[str] = mapped_column(String(64), nullable=False)
    provider_type: Mapped[str] = mapped_column(String(64), nullable=False)
    scope: Mapped[str] = mapped_column(String(32), nullable=False, default="global")
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    display_name: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    capabilities: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    settings: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    credentials_ref: Mapped[str] = mapped_column(String(256), nullable=False, default="")
    encrypted_api_key: Mapped[str] = mapped_column(Text, nullable=False, default="")
    health_status: Mapped[str] = mapped_column(String(32), nullable=False, default="unknown")
    health_error_type: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    health_error: Mapped[str] = mapped_column(Text, nullable=False, default="")
    health_duration_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    health_checked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    metadata_json: Mapped[dict] = mapped_column(
        "metadata", JSON, nullable=False, default=dict
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
