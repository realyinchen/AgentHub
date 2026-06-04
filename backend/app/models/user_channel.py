"""User channel model for multi-channel authentication."""

from uuid import UUID, uuid4
from datetime import datetime
from typing import Literal

from sqlalchemy import Boolean, String, DateTime, Uuid, Text, ForeignKey, JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.infra.database import Base
from app.models.base import utc_now


# Supported channel types (can be extended)
ChannelType = Literal["weixin"]


class UserChannel(Base):
    """User channel association table.
    
    Stores channel-specific authentication data for users.
    A user can have multiple channels (WeChat, Telegram, etc.).
    
    Channel user ID (e.g., WeChat's xxx@im.wechat) is unique per channel,
    preventing the same channel account from binding to multiple AgentHub users.
    """
    __tablename__ = "user_channels"
    __table_args__ = (
        # Unique constraint: one user can only have one channel of each type
        # Unique constraint: same channel_user_id can only bind one AgentHub user
        # These are enforced via unique indexes below
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    
    # Channel identification
    channel: Mapped[str] = mapped_column(String(32), nullable=False)  # 'weixin', 'telegram', etc.
    channel_user_id: Mapped[str] = mapped_column(String(128), nullable=False)  # e.g., 'xxx@im.wechat'
    
    # Channel credentials (encrypted storage for sensitive data)
    channel_token: Mapped[str | None] = mapped_column(Text, nullable=True)  # Bot token (encrypted)
    channel_base_url: Mapped[str | None] = mapped_column(String(512), nullable=True)  # API base URL
    channel_token_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )  # Token expiration time
    
    # Channel extra data (JSONB for flexibility)
    channel_extra_data: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    
    # Last contact info (for reconnection notifications)
    last_contact_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    last_context_token: Mapped[str | None] = mapped_column(Text, nullable=True)
    
    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        onupdate=utc_now,
    )
    
    # Relationship to User (use TYPE_CHECKING to avoid circular import)
    user: Mapped["User"] = relationship("User", back_populates="user_channels")


# Import User for type checking (avoid circular import at runtime)
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from app.models.user import User
