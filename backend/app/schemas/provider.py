from pydantic import BaseModel, Field
from datetime import datetime


class ProviderInfo(BaseModel):
    """Provider information for frontend display"""

    provider: str = Field(..., description="Provider name, e.g. 'dashscope', 'zai'")
    has_api_key: bool = Field(False, description="Whether API key is configured")
    base_url: str | None = Field(None, description="Base URL for OpenAI-Compatible providers")
    is_openai_compatible: bool = Field(False, description="Whether this is an OpenAI-Compatible provider")
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class ProvidersResponse(BaseModel):
    """Response for listing all providers"""

    providers: list[ProviderInfo]


class ProviderUpdateRequest(BaseModel):
    """Request to update a provider"""

    provider: str = Field(..., description="Provider name")
    api_key: str | None = Field(None, description="API key (will be encrypted)")
    base_url: str | None = Field(None, description="Base URL for OpenAI-Compatible providers")
