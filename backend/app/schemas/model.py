from pydantic import BaseModel
from datetime import datetime
from typing import Optional, Literal


# ==================== Model Schemas ====================


class ModelBase(BaseModel):
    """Model base fields"""

    provider: str  # e.g. "dashscope", "zai"
    model_type: Literal["llm", "vlm", "embedding"] = "llm"
    model_id: str  # e.g. "qwen3.5-27b" (without provider prefix)
    model_name: str  # e.g. "qwen3.5-27b" (display name)


class ModelCreate(ModelBase):
    """Create model"""

    api_key: Optional[str] = None
    thinking: bool = False
    is_default: bool = False
    is_active: bool = True


class ModelUpdate(BaseModel):
    """Update model"""

    provider: Optional[str] = None
    model_type: Optional[Literal["llm", "vlm", "embedding"]] = None
    model_name: Optional[str] = None
    api_key: Optional[str] = None
    thinking: Optional[bool] = None
    is_default: Optional[bool] = None
    is_active: Optional[bool] = None


class ModelInDB(BaseModel):
    """Model database model (without api_key)"""

    provider: str
    model_type: str
    model_id: str
    model_name: str
    has_api_key: bool  # don't return actual API Key, just whether it exists
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

    model_id: str


class ModelUpdateRequest(BaseModel):
    """Update model request (with model_id in body)"""

    model_id: str
    provider: Optional[str] = None
    model_type: Optional[Literal["llm", "vlm", "embedding"]] = None
    model_name: Optional[str] = None
    api_key: Optional[str] = None
    thinking: Optional[bool] = None
    is_default: Optional[bool] = None
    is_active: Optional[bool] = None


class DeleteModelRequest(BaseModel):
    """Delete model request (with model_id in body)"""

    model_id: str


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
