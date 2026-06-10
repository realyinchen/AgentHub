import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Integer, Numeric, String, Text, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.infra.database.base import Base
from app.models.base import utc_now


class Book(Base):
    """Book metadata cached from public sources such as Douban search results."""

    __tablename__ = "books"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    title: Mapped[str] = mapped_column(String(256), nullable=False)
    subtitle: Mapped[str | None] = mapped_column(String(256), nullable=True)
    authors: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    tags: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    rating: Mapped[Decimal | None] = mapped_column(Numeric(3, 1), nullable=True)
    rating_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cover_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    source_name: Mapped[str] = mapped_column(String(64), nullable=False, default="web")
    source_url: Mapped[str | None] = mapped_column(String(1024), unique=True)
    external_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    raw_data: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
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


class BookInteraction(Base):
    """User feedback for books and recommendation results."""

    __tablename__ = "book_interactions"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    book_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("books.id", ondelete="SET NULL"), nullable=True
    )
    book_title: Mapped[str | None] = mapped_column(String(256), nullable=True)
    interaction_type: Mapped[str] = mapped_column(String(32), nullable=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    rating: Mapped[int | None] = mapped_column(Integer, nullable=True)
    raw_data: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        onupdate=utc_now,
    )


class UserPreferenceProfile(Base):
    """Structured long-term reading preference profile for a user."""

    __tablename__ = "user_preference_profiles"

    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    preferred_tags: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list
    )
    disliked_tags: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    favorite_authors: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list
    )
    disliked_authors: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list
    )
    notes: Mapped[str] = mapped_column(Text, nullable=False, default="")
    profile_summary: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        onupdate=utc_now,
    )
