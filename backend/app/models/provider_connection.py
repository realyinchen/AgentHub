import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, JSON, String, Text, Uuid, Boolean
from sqlalchemy.orm import Mapped, mapped_column

from app.infra.database.base import Base
from app.models.base import utc_now


class ProviderConnection(Base):
    """Concrete endpoint/account configuration for a provider adapter.

    Provider rows describe protocol/adapter behavior. Connections own mutable
    endpoint credentials such as API keys and base URLs.
    """

    __tablename__ = "provider_connections"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    provider: Mapped[str] = mapped_column(
        String(64), ForeignKey("providers.provider"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    preset_type: Mapped[str] = mapped_column(String(32), nullable=False, default="default")
    api_key: Mapped[str] = mapped_column(Text, nullable=False, default="")
    base_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    extra_headers_json: Mapped[dict] = mapped_column(
        JSON, nullable=False, default=dict
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        onupdate=utc_now,
    )

