from sqlalchemy import String, Boolean, DateTime, Text
from sqlalchemy.orm import Mapped, mapped_column
from datetime import datetime, timezone

from app.infra.database.base import Base


def utc_now():
    return datetime.now(timezone.utc)


class Provider(Base):
    """
    Provider configuration table.
    Stores API keys and base URLs for each model provider.

    Fields:
        provider: Provider name (primary key), e.g. "dashscope", "zai", "openai-compatible"
        api_key: Encrypted API key for the provider
        base_url: Base URL for OpenAI-Compatible providers (e.g., Ollama, LM Studio)
        is_openai_compatible: Whether this provider uses OpenAI-compatible API format
    """

    __tablename__ = "providers"

    provider: Mapped[str] = mapped_column(
        String(64), primary_key=True
    )  # e.g. "dashscope", "zai", "openai-compatible"
    api_key: Mapped[str] = mapped_column(
        Text, nullable=False, default=""
    )  # encrypted API key
    base_url: Mapped[str | None] = mapped_column(
        String(512), nullable=True
    )  # base URL for OpenAI-Compatible providers
    is_openai_compatible: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
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
