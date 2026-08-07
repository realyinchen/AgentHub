from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator
from datetime import datetime
from typing import Any, Optional, Literal

# ==================== Mixin: Mutable Fields ====================


class ModelMutableFields(BaseModel):
    """Fields that can be set on creation and partially updated later.

    All fields are Optional with sensible defaults, enabling both:
    - ModelCreate: inherits defaults directly for new models
    - ModelUpdateRequest: inherits Optional types; model_dump(exclude_unset=True)
      naturally excludes fields that the client didn't send
    """

    thinking: Optional[bool] = Field(
        default=False,
        description="Configured default thinking mode for runtime requests.",
    )
    is_default: Optional[bool] = False
    is_active: Optional[bool] = True


# ==================== Model Schemas ====================


class ModelBase(BaseModel):
    """Model base fields (immutable identity fields)."""

    provider: str | None = None  # legacy/provider adapter key
    connection_id: Optional[str] = None
    model_type: Literal["llm", "vlm", "embedding"] = "llm"
    model_id: str  # e.g. "qwen3.5-32b" (without provider prefix)


class ModelCreate(ModelBase, ModelMutableFields):
    """Create a new model. Mutable fields inherit sensible defaults from ModelMutableFields."""

    pass


class ModelUpdateRequest(ModelMutableFields):
    """Update an existing model (partial update via PATCH /models/{model_id}).

    The model_id comes from the URL path, not the request body.
    Inherits mutable fields from ModelMutableFields so model_dump(exclude_unset=True)
    naturally excludes fields the client didn't send.
    """

    model_id: Optional[str] = None  # New model_id if changing
    provider: Optional[str] = None
    connection_id: Optional[str] = None
    model_type: Optional[Literal["llm", "vlm", "embedding"]] = None


class ModelInDB(BaseModel):
    """Model database model"""

    id: str  # UUID primary key
    provider: str
    connection_id: Optional[str] = None
    model_type: str
    model_id: str
    thinking: bool
    is_default: bool
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)

    @field_validator("id", "connection_id", mode="before")
    @classmethod
    def convert_uuid_to_str(cls, v):
        """Convert UUID to string automatically."""
        if isinstance(v, UUID):
            return str(v)
        return v


class ModelCapabilityStatus(BaseModel):
    """Latest observed runtime capability for a configured model."""

    id: str
    model_id: str
    provider: str
    provider_model_id: str
    checked_at: datetime
    probe_kind: Literal["chat", "embedding"] = "chat"
    probe_ok: bool = False
    embedding_dimensions: Optional[int] = Field(default=None, ge=1)
    error_category: Optional[
        Literal["network", "auth", "model", "rate_limit", "dimension", "provider"]
    ] = None
    # Deprecated compatibility field. New consumers should use probe_ok.
    chat_ok: bool
    thinking_request_ok: Optional[bool] = None
    reasoning_text_ok: Optional[bool] = None
    streaming_reasoning_ok: Optional[bool] = None
    reasoning_field_path: Optional[str] = None
    latency_ms: Optional[int] = None
    error_type: Optional[str] = None
    last_error: Optional[str] = None
    raw_summary: dict[str, Any] = Field(default_factory=dict)

    model_config = ConfigDict(from_attributes=True)

    @field_validator("id", "model_id", mode="before")
    @classmethod
    def convert_uuid_to_str(cls, v):
        """Convert UUID to string automatically."""
        if isinstance(v, UUID):
            return str(v)
        return v


class ModelInfo(ModelInDB):
    """Model info for frontend model selector"""

    model_uuid: Optional[str] = None
    provider_key: Optional[str] = None
    connection_name: Optional[str] = None
    provider_model_id: Optional[str] = None
    display_name: Optional[str] = None
    thinking_requested: Optional[bool] = None
    capability: Optional[ModelCapabilityStatus] = None


class ModelValidationRequest(BaseModel):
    """Request body for model runtime capability validation."""

    check_thinking: bool = Field(
        default=True,
        description="Whether to send a real thinking/reasoning request.",
    )


# ==================== Response Schemas ====================


class ModelsResponse(BaseModel):
    """Models list response"""

    models: list[ModelInfo]
    default_llm: Optional[str] = None
    default_vlm: Optional[str] = None
    default_embedding: Optional[str] = None


# ==================== Request Schemas ====================


class SetDefaultModelRequest(BaseModel):
    """Set default model request"""

    id: str  # UUID primary key


class DeleteModelRequest(BaseModel):
    """Delete model request (with id in body)"""

    id: str  # UUID primary key


class TestConnectionRequest(BaseModel):
    """Test model connection request"""

    provider: str  # e.g. "dashscope", "zai"
    model_id: str  # e.g. "qwen3.5-27b"
    api_key: str
    model_type: Literal["llm", "vlm", "embedding"] = "llm"


class TestConnectionResponse(BaseModel):
    """Test model connection response"""

    success: bool
    message: str


# ==================== Thinking Mode ====================


class ThinkingModeStatus(BaseModel):
    """Legacy response for the default model's configured request mode."""

    available: bool = Field(
        description="Whether thinking mode is configured for the default model"
    )
