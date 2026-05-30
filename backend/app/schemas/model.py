from uuid import UUID

from pydantic import BaseModel, ConfigDict, field_validator
from datetime import datetime
from typing import Optional, Literal




# ==================== Mixin: Mutable Fields ====================


class ModelMutableFields(BaseModel):
    """Fields that can be set on creation and partially updated later.

    All fields are Optional with sensible defaults, enabling both:
    - ModelCreate: inherits defaults directly for new models
    - ModelUpdateRequest: inherits Optional types; model_dump(exclude_unset=True)
      naturally excludes fields that the client didn't send
    """

    thinking: Optional[bool] = False
    is_default: Optional[bool] = False
    is_active: Optional[bool] = True


# ==================== Model Schemas ====================


class ModelBase(BaseModel):
    """Model base fields (immutable identity fields)."""

    provider: str  # e.g. "dashscope", "zai"
    model_type: Literal["llm", "vlm"] = "llm"
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
    model_type: Optional[Literal["llm", "vlm"]] = None


class ModelInDB(BaseModel):
    """Model database model"""

    id: str  # UUID primary key
    provider: str
    model_type: str
    model_id: str
    thinking: bool
    is_default: bool
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)

    @field_validator("id", mode="before")
    @classmethod
    def convert_uuid_to_str(cls, v):
        """Convert UUID to string automatically."""
        if isinstance(v, UUID):
            return str(v)
        return v


class ModelInfo(ModelInDB):
    """Model info for frontend model selector"""

    pass


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
    model_type: Literal["llm", "vlm"] = "llm"


class TestConnectionResponse(BaseModel):
    """Test model connection response"""

    success: bool
    message: str
