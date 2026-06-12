from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator
from datetime import datetime


class ProviderInfo(BaseModel):
    """Provider information for frontend display"""

    provider: str = Field(..., description="Provider name, e.g. 'dashscope', 'zai'")
    provider_key: str | None = Field(
        None, description="Stable provider key used to select the adapter"
    )
    display_name: str | None = Field(None, description="Human-readable provider name")
    adapter_type: str | None = Field(None, description="Provider adapter type")
    supports_connections: bool = Field(True, description="Whether provider has connections")
    enabled: bool = Field(True, description="Whether provider is enabled")
    legacy: bool = Field(False, description="Whether provider is legacy-only")
    connection_count: int = Field(0, description="Number of configured connections")
    model_count: int = Field(0, description="Number of configured models")
    has_api_key: bool = Field(False, description="Whether API key is configured")
    base_url: str | None = Field(
        None, description="Base URL for OpenAI-Compatible providers"
    )
    is_openai_compatible: bool = Field(
        False, description="Whether this is an OpenAI-Compatible provider"
    )
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ProvidersResponse(BaseModel):
    """Response for listing all providers"""

    contract_version: str = "provider-connection-model-v1"
    providers: list[ProviderInfo]


class ProviderUpdateRequest(BaseModel):
    """Request to update a provider"""

    provider: str = Field(..., description="Provider name")
    api_key: str | None = Field(None, description="API key (will be encrypted)")
    base_url: str | None = Field(
        None, description="Base URL for OpenAI-Compatible providers"
    )


class ProviderConnectionInfo(BaseModel):
    """Concrete endpoint/account under one provider adapter."""

    connection_id: str
    provider_key: str
    name: str
    preset_type: str
    base_url: str | None = None
    has_api_key: bool = False
    enabled: bool = True
    model_count: int = 0
    extra_headers_json: dict = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)

    @field_validator("connection_id", mode="before")
    @classmethod
    def convert_uuid_to_str(cls, v):
        if isinstance(v, UUID):
            return str(v)
        return v


class ProviderConnectionsResponse(BaseModel):
    connections: list[ProviderConnectionInfo]


class ProviderConnectionCreate(BaseModel):
    provider_key: str = Field(..., description="Provider adapter key")
    name: str = Field(..., min_length=1, max_length=128)
    preset_type: str = Field("custom", max_length=32)
    api_key: str | None = None
    base_url: str | None = None
    enabled: bool = True
    extra_headers_json: dict | None = None


class ProviderConnectionUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=128)
    preset_type: str | None = Field(None, max_length=32)
    api_key: str | None = None
    clear_api_key: bool = False
    base_url: str | None = None
    enabled: bool | None = None
    extra_headers_json: dict | None = None
