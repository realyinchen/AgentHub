"""Model and provider management endpoints — /models resource group.

Routes:
    GET    /models                          — Get active models (for dropdown)
    GET    /models?include_inactive=true    — Get all models (for config page)
    POST   /models                          — Create a new model
    PATCH  /models/{model_id}               — Update model config (partial update)
    DELETE /models/{model_id}               — Delete a model
    GET    /models/providers                — List all providers
    PATCH  /models/providers/{provider_name}— Update provider API key / base URL
    GET    /models/thinking-mode            — Thinking-mode availability status
"""

import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.dependencies import get_db
from app.crud import model as model_crud
from app.crud import model_capability as capability_crud
from app.crud import provider as provider_crud
from app.infra.llm import get_model_manager
from app.schemas.model import (
    ModelCapabilityStatus,
    ModelCreate,
    ModelInfo,
    ModelValidationRequest,
    ModelsResponse,
    ModelUpdateRequest,
    ThinkingModeStatus,
)
from app.schemas.provider import (
    ProviderInfo,
    ProvidersResponse,
    ProviderUpdateRequest,
)
from app.services.model_validation import (
    ModelValidationError,
    validate_model_capability,
)
from app.utils.crypto import encrypt_api_key

logger = logging.getLogger(__name__)

api_router = APIRouter(prefix="/models", tags=["Models"])


# ── Model CRUD ───────────────────────────────────────────────────────────────


@api_router.get("", response_model=ModelsResponse)
async def get_available_models(
    include_inactive: bool = Query(
        False,
        description="When true, return all models including inactive ones (for config page)",
    ),
    db: AsyncSession = Depends(get_db),
) -> ModelsResponse:
    """Get available models.

    Default: only returns models with provider API key configured (for frontend dropdown).
    With ``?include_inactive=true``: returns all models (for configuration page).
    Models are sorted by provider (alphabetically), then by model_id.
    """
    return await model_crud.get_models_response(db, active_only=not include_inactive)


@api_router.post("", response_model=ModelInfo, status_code=status.HTTP_201_CREATED)
async def create_model(
    model_data: ModelCreate,
    db: AsyncSession = Depends(get_db),
) -> ModelInfo:
    """Create a new model."""
    existing = await model_crud.get_model(db, model_data.model_id)
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="model_id_exists",
        )

    create_data = model_data.model_dump()
    create_data.pop("is_default", None)
    new_model = await model_crud.create_model(db, create_data)

    if model_data.is_default:
        new_model = await model_crud.set_default_model_by_model_id(
            db, str(new_model.model_id)
        )

    await get_model_manager().refresh()
    return ModelInfo.model_validate(new_model)


@api_router.patch("/{model_id}", response_model=ModelInfo)
async def update_model(
    model_id: uuid.UUID,
    request: ModelUpdateRequest,
    db: AsyncSession = Depends(get_db),
) -> ModelInfo:
    """Update model configuration (partial update via PATCH).

    Only the fields present in the request body will be updated.
    Set ``is_default: true`` to make this the default model for its type.
    """
    existing = await model_crud.get_model_by_id(db, model_id)
    if not existing:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Model with id '{model_id}' not found",
        )

    update_dict = request.model_dump(exclude_unset=True, exclude={"id"})

    updated_model = await model_crud.update_model_by_id(db, model_id, update_dict)

    if updated_model and update_dict.get("is_default"):
        updated_model = await model_crud.set_default_model_by_id(db, model_id)

    await get_model_manager().refresh()
    return ModelInfo.model_validate(updated_model)


@api_router.delete("/{model_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_model(
    model_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> None:
    """Delete a model."""
    deleted = await model_crud.delete_model_by_id(db, model_id)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Model with id '{model_id}' not found",
        )

    await get_model_manager().refresh()


@api_router.post("/{model_id}/validate", response_model=ModelCapabilityStatus)
async def validate_model(
    model_id: uuid.UUID,
    request: ModelValidationRequest | None = None,
    db: AsyncSession = Depends(get_db),
) -> ModelCapabilityStatus:
    """Run a real chat + thinking capability check for one configured model."""
    try:
        check = await validate_model_capability(
            db,
            model_id,
            check_thinking=True if request is None else request.check_thinking,
        )
    except ModelValidationError as exc:
        detail = str(exc)
        raise HTTPException(
            status_code=(
                status.HTTP_404_NOT_FOUND
                if detail == "model_not_found"
                else status.HTTP_400_BAD_REQUEST
            ),
            detail=detail,
        ) from exc

    return ModelCapabilityStatus.model_validate(check)


@api_router.get("/{model_id}/capabilities", response_model=ModelCapabilityStatus | None)
async def get_model_capability(
    model_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> ModelCapabilityStatus | None:
    """Get the latest observed capability check for one model."""
    existing = await model_crud.get_model_by_id(db, model_id)
    if not existing:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Model with id '{model_id}' not found",
        )

    check = await capability_crud.get_latest_capability_check(db, model_id)
    if check is None:
        return None
    return ModelCapabilityStatus.model_validate(check)


# ── Provider (sub-resource of models) ────────────────────────────────────────


def _provider_to_info(provider) -> ProviderInfo:
    """Convert database provider to ProviderInfo."""
    return ProviderInfo(
        provider=provider.provider,
        has_api_key=bool(provider.api_key),
        base_url=provider.base_url,
        is_openai_compatible=provider.is_openai_compatible,
        created_at=provider.created_at,
        updated_at=provider.updated_at,
    )


@api_router.get("/providers", response_model=ProvidersResponse)
async def get_all_providers(
    db: AsyncSession = Depends(get_db),
) -> ProvidersResponse:
    """Get all providers with their configuration status.

    Returns providers sorted alphabetically by name.
    """
    providers = await provider_crud.get_all_providers(db)
    return ProvidersResponse(providers=[_provider_to_info(p) for p in providers])


@api_router.patch("/providers/{provider_name}", response_model=ProviderInfo)
async def update_provider(
    provider_name: str,
    request: ProviderUpdateRequest,
    db: AsyncSession = Depends(get_db),
) -> ProviderInfo:
    """Update a provider's API key and/or base URL (partial update via PATCH).

    Only allows updating existing providers (no creation).
    """
    existing = await provider_crud.get_provider(db, provider_name)
    if not existing:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Provider '{provider_name}' not found",
        )

    update_data: dict = {}
    if request.api_key is not None:
        update_data["api_key"] = encrypt_api_key(request.api_key)
    if request.base_url is not None:
        update_data["base_url"] = request.base_url

    if not update_data:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No fields to update",
        )

    updated = await provider_crud.update_provider(db, provider_name, update_data)
    if not updated:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update provider",
        )

    await get_model_manager().refresh()
    return _provider_to_info(updated)


# ── Thinking mode ─────────────────────────────────────────────────────────────


@api_router.get("/thinking-mode", response_model=ThinkingModeStatus)
async def get_thinking_mode_status() -> ThinkingModeStatus:
    """Check if thinking mode is available."""
    return ThinkingModeStatus(
        available=get_model_manager().is_thinking_mode_available()
    )
