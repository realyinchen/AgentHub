"""User model for AgentHub authentication."""

from uuid import UUID, uuid4
from datetime import datetime

from sqlalchemy import Boolean, String, DateTime, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.infra.database import Base
from app.models.base import utc_now


# Import for type checking (avoid circular import at runtime)
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.models.user_channel import UserChannel


class User(Base):
    """Main user table for AgentHub.

    Users can be:
    - Mock users (Jack/Rose) for demo/testing
    - Real users authenticated via channels (WeChat, etc.)

    Channel-specific data is stored in UserChannel table.
    """

    __tablename__ = "users"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    display_name: Mapped[str] = mapped_column(String(64), nullable=False)
    is_mock_user: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        onupdate=utc_now,
    )

    # Relationship to UserChannel
    user_channels: Mapped[list["UserChannel"]] = relationship(
        "UserChannel", back_populates="user", cascade="all, delete-orphan"
    )
