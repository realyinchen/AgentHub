from sqlalchemy import Column, String, Boolean, DateTime, Text
from sqlalchemy.sql import func

from app.database.base import Base


class Model(Base):
    """
    Model configuration table.
    Users can configure all model API keys in this table.
    Supports LLM, VLM, and embedding models.

    Fields:
        provider: e.g. "dashscope", "zai"
        api_key: encrypted by frontend
        model_type: llm, vlm, embedding
        model_id: model name without provider prefix, e.g. "qwen3.5-27b"
        model_name: display name, e.g. "qwen3.5-27b"
        thinking: whether supports thinking mode
        is_default: default model for this model_type
        is_active: whether this model is active

    Note: litellm model is built as "provider/model_id", e.g. "dashscope/qwen3.5-27b"
    """

    __tablename__ = "models"

    provider = Column(String(64), nullable=False)  # e.g. "dashscope", "zai"
    api_key = Column(Text, nullable=False, default="")  # encrypted by frontend
    model_type = Column(
        String(16), nullable=False, default="llm"
    )  # llm, vlm, embedding
    model_id = Column(String(128), primary_key=True)  # e.g. "dashscope/qwen3.5-27b"
    model_name = Column(String(64), nullable=False)  # e.g. "qwen3.5-27b"
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
