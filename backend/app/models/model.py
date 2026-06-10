import uuid
from datetime import datetime

from sqlalchemy import String, Boolean, DateTime, ForeignKey, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.infra.database.base import Base
from app.models.base import utc_now


class Model(Base):
    """
    Model configuration table.
    Users can configure all models in this table.
    Supports LLM, VLM, and embedding models.

    Fields:
        id: UUID primary key
        provider: e.g. "dashscope", "zai", references providers table
        model_type: llm, vlm, embedding
        model_id: model identifier without provider prefix, e.g. "qwen3.5-32b"
        thinking: whether supports thinking mode
        is_default: default model for this model_type
        is_active: whether this model is active

    Note: model_id is stored as plain model name, e.g. "qwen3.5-32b".
          The full litellm model name "provider/model_id" is assembled at runtime.
    Note: API keys are now stored in the providers table
    """

    __tablename__ = "models"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, default=uuid.uuid4
    )  # UUID primary key
    provider: Mapped[str] = mapped_column(
        String(64), ForeignKey("providers.provider"), nullable=False
    )  # e.g. "dashscope", "zai" - FK to providers table
    model_type: Mapped[str] = mapped_column(
        String(16), nullable=False, default="llm"
    )  # llm, vlm, embedding
    model_id: Mapped[str] = mapped_column(
        String(128), nullable=False, unique=True
    )  # e.g. "qwen3.5-32b" (without provider prefix)
    thinking: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )  # whether supports thinking mode
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
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
