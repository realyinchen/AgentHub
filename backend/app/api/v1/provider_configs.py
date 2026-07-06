"""App-owned provider integration configuration endpoints."""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.dependencies import get_db
from app.services.provider_config import (
    AppProviderConfig,
    AppProviderConfigList,
    AppProviderConfigUpdate,
    check_provider_health_in_db,
    get_provider_config_from_db,
    list_provider_configs_from_db,
    update_provider_config_in_db,
)

api_router = APIRouter(prefix="/provider-configs", tags=["Provider Configs"])


@api_router.get("", response_model=AppProviderConfigList)
async def list_provider_configs(
    scope: str = Query("global"),
    db: AsyncSession = Depends(get_db),
) -> AppProviderConfigList:
    """List app provider integrations such as mem0 and gbrain."""
    return await list_provider_configs_from_db(db, scope=scope)


@api_router.get("/{provider_key}", response_model=AppProviderConfig)
async def get_provider_config(
    provider_key: str,
    scope: str = Query("global"),
    db: AsyncSession = Depends(get_db),
) -> AppProviderConfig:
    """Get one app provider integration config."""
    config = await get_provider_config_from_db(db, provider_key, scope=scope)
    if config is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="provider_config_not_found",
        )
    return config


@api_router.patch("/{provider_key}", response_model=AppProviderConfig)
async def update_provider_config(
    provider_key: str,
    update: AppProviderConfigUpdate,
    scope: str = Query("global"),
    db: AsyncSession = Depends(get_db),
) -> AppProviderConfig:
    """Update one app provider config without ever returning submitted secrets."""
    config = await update_provider_config_in_db(db, provider_key, update, scope=scope)
    if config is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="provider_config_not_found",
        )
    return config


@api_router.post("/{provider_key}/health", response_model=AppProviderConfig)
async def check_provider_health(
    provider_key: str,
    scope: str = Query("global"),
    db: AsyncSession = Depends(get_db),
) -> AppProviderConfig:
    """Refresh app provider health without writing memory or research evidence."""
    config = await check_provider_health_in_db(db, provider_key, scope=scope)
    if config is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="provider_config_not_found",
        )
    return config
