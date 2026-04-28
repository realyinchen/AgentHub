from sqlalchemy import Column, String, Boolean, DateTime, Text
from datetime import datetime, timezone

from app.database.base import Base


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

    provider = Column(
        String(64), primary_key=True
    )  # e.g. "dashscope", "zai", "openai-compatible"
    api_key = Column(Text, nullable=False, default="")  # encrypted API key
    base_url = Column(
        String(512), nullable=True
    )  # base URL for OpenAI-Compatible providers
    is_openai_compatible = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        onupdate=utc_now,
    )
