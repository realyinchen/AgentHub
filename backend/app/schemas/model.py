from pydantic import BaseModel
from datetime import datetime
from typing import Optional, Literal


# ==================== Model Schemas ====================


class ModelBase(BaseModel):
    """Model base fields"""

    provider: str  # e.g. "dashscope", "zai"
    model_type: Literal["llm", "vlm", "embedding"] = "llm"
    model_id: str  # e.g. "dashscope/qwen3.5-27b" (with provider prefix)


class ModelCreate(ModelBase):
    """Create model"""

    thinking: bool = False
    is_default: bool = False
    is_active: bool = True


class ModelUpdate(BaseModel):
    """Update model"""

    provider: Optional[str] = None
    model_type: Optional[Literal["llm", "vlm", "embedding"]] = None
    model_id: Optional[str] = None  # Allow updating model_id (primary key)
    thinking: Optional[bool] = None
    is_default: Optional[bool] = None
    is_active: Optional[bool] = None


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

    model_config = {"from_attributes": True}


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


class ModelUpdateRequest(BaseModel):
    """Update model request (with id in body)"""

    id: str  # UUID primary key (used to find the record)
    model_id: Optional[str] = None  # New model_id if changing
    provider: Optional[str] = None
    model_type: Optional[Literal["llm", "vlm", "embedding"]] = None
    thinking: Optional[bool] = None
    is_default: Optional[bool] = None
    is_active: Optional[bool] = None


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


class RefreshResponse(BaseModel):
    """Refresh cache response"""

    success: bool
    message: str
    models_count: int = 0


class ProvidersResponse(BaseModel):
    """Available providers response"""

    providers: list[str]
