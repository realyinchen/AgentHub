import uuid
from sqlalchemy import Column, String, Boolean, DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func

from app.database.base import Base


class Model(Base):
    """
    Model configuration table.
    Users can configure all models in this table.
    Supports LLM, VLM, and embedding models.

    Fields:
        id: UUID primary key
        provider: e.g. "dashscope", "zai", references providers table
        model_type: llm, vlm, embedding
        model_id: full model identifier with provider prefix, e.g. "dashscope/qwen3.5-27b"
        thinking: whether supports thinking mode
        is_default: default model for this model_type
        is_active: whether this model is active

    Note: model_id is stored as "provider/model_id" format, e.g. "dashscope/qwen3.5-27b"
    Note: API keys are now stored in the providers table
    """

    __tablename__ = "models"

    id = Column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )  # UUID primary key
    provider = Column(
        String(64), ForeignKey("providers.provider"), nullable=False
    )  # e.g. "dashscope", "zai" - FK to providers table
    model_type = Column(
        String(16), nullable=False, default="llm"
    )  # llm, vlm, embedding
    model_id = Column(
        String(128), nullable=False, unique=True
    )  # e.g. "dashscope/qwen3.5-27b" (with provider prefix)
    thinking = Column(
        Boolean, nullable=False, default=False
    )  # whether supports thinking mode
    is_default = Column(Boolean, nullable=False, default=False)
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
