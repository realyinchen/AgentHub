from fastapi import APIRouter, HTTPException, status, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.dependencies import get_db
from app.crud import provider as crud
from app.schemas.provider import (
    ProviderInfo,
    ProvidersResponse,
    ProviderUpdateRequest,
)
from app.utils.crypto import encrypt_api_key

api_router = APIRouter(prefix="/providers", tags=["Providers"])


def provider_to_info(provider) -> ProviderInfo:
    """Convert database provider to ProviderInfo"""
    return ProviderInfo(
        provider=provider.provider,
        has_api_key=bool(provider.api_key),
        base_url=provider.base_url,
        is_openai_compatible=provider.is_openai_compatible,
        created_at=provider.created_at,
        updated_at=provider.updated_at,
    )


@api_router.get("/", response_model=ProvidersResponse)
async def get_all_providers(db: AsyncSession = Depends(get_db)) -> ProvidersResponse:
    """
    Get all providers with their configuration status.
    Returns providers sorted alphabetically by name.
    """
    providers = await crud.get_all_providers(db)
    return ProvidersResponse(providers=[provider_to_info(p) for p in providers])


@api_router.post("/update", response_model=ProviderInfo)
async def update_provider(
    request: ProviderUpdateRequest, db: AsyncSession = Depends(get_db)
) -> ProviderInfo:
    """
    Update a provider's API key and/or base URL.
    Only allows updating existing providers (no creation).
    """
    # Check if provider exists
    existing = await crud.get_provider(db, request.provider)
    if not existing:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Provider '{request.provider}' not found",
        )

    # Build update data
    update_data = {}
    if request.api_key is not None:
        # Encrypt API key before storing
        update_data["api_key"] = encrypt_api_key(request.api_key)
    if request.base_url is not None:
        update_data["base_url"] = request.base_url

    if not update_data:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No fields to update",
        )

    # Update provider
    updated = await crud.update_provider(db, request.provider, update_data)
    if not updated:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update provider",
        )

    return provider_to_info(updated)
