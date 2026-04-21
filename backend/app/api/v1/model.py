import os
import uuid
from typing import Optional
from fastapi import APIRouter, HTTPException, status, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import adb_manager
from app.crud import model as crud
from app.schemas.model import (
    ModelCreate,
    ModelInfo,
    ModelsResponse,
    SetDefaultModelRequest,
    ModelUpdateRequest,
    DeleteModelRequest,
    RefreshResponse,
    ProvidersResponse,
)

api_router = APIRouter(prefix="/models", tags=["Models"])


async def get_db():
    """Dependency to provide async session"""
    async with adb_manager.session() as session:
        yield session


def model_to_info(model) -> ModelInfo:
    """Convert database model to ModelInfo"""
    return ModelInfo(
        id=str(model.id),
        provider=model.provider,
        model_type=model.model_type,
        model_id=model.model_id,
        thinking=model.thinking,
        is_default=model.is_default,
        is_active=model.is_active,
        created_at=model.created_at,
        updated_at=model.updated_at,
    )


@api_router.get("/providers", response_model=ProvidersResponse)
async def get_providers() -> ProvidersResponse:
    """
    Get available model providers.
    Providers are configured in .env as MODEL_PROVIDERS=["dashscope", "zai"]
    """
    providers_str = os.getenv("MODEL_PROVIDERS", '["dashscope", "zai"]')
    try:
        import json

        providers = json.loads(providers_str)
    except Exception:
        providers = ["dashscope", "zai"]

    return ProvidersResponse(providers=providers)


def get_first_model_by_type(models: list, model_type: str) -> Optional[str]:
    """
    Get the first model of a specific type from a sorted list.
    Models are already sorted by provider (alphabetically), then by model_id.
    Returns the model_id of the first matching model, or None if not found.
    """
    for model in models:
        if model.model_type == model_type:
            return model.model_id
    return None


def _build_models_response(models: list) -> ModelsResponse:
    """
    Build ModelsResponse from model list.

    Optimized to extract default models from the list instead of additional DB queries.
    Default model selection logic:
    - If a model has is_default=True, use that
    - Otherwise, use the first model of that type (sorted alphabetically by provider)
    """
    # Convert to ModelInfo
    model_infos = [model_to_info(m) for m in models]

    # Extract default model IDs from the list (no additional DB query needed)
    default_llm_id = None
    default_vlm_id = None
    default_embedding_id = None

    for m in models:
        if getattr(m, "is_default", False):
            model_type = getattr(m, "model_type", "llm")
            if model_type == "llm" and default_llm_id is None:
                default_llm_id = str(m.model_id)
            elif model_type == "vlm" and default_vlm_id is None:
                default_vlm_id = str(m.model_id)
            elif model_type == "embedding" and default_embedding_id is None:
                default_embedding_id = str(m.model_id)

    # If no default model is set, use the first model of that type
    if default_llm_id is None:
        default_llm_id = get_first_model_by_type(models, "llm")
    if default_vlm_id is None:
        default_vlm_id = get_first_model_by_type(models, "vlm")
    if default_embedding_id is None:
        default_embedding_id = get_first_model_by_type(models, "embedding")

    return ModelsResponse(
        models=model_infos,
        default_llm=default_llm_id,
        default_vlm=default_vlm_id,
        default_embedding=default_embedding_id,
    )


@api_router.get("/", response_model=ModelsResponse)
async def get_available_models(db: AsyncSession = Depends(get_db)) -> ModelsResponse:
    """
    Get all available models (for frontend dropdown).
    Only returns models with provider API key configured.
    Models are sorted by provider (alphabetically), then by model_id.
    """
    models = await crud.get_models_with_provider_config(db)
    return _build_models_response(models)


@api_router.get("/all", response_model=ModelsResponse)
async def get_all_models(db: AsyncSession = Depends(get_db)) -> ModelsResponse:
    """
    Get all models (for configuration page).
    Models are sorted by provider (alphabetically), then by model_id.
    """
    models = await crud.get_all_models(db, active_only=False)
    return _build_models_response(models)


@api_router.post("/", response_model=ModelInfo, status_code=status.HTTP_201_CREATED)
async def create_model(
    model_data: ModelCreate, db: AsyncSession = Depends(get_db)
) -> ModelInfo:
    """Create a new model"""
    # Check if model_id already exists
    existing = await crud.get_model(db, model_data.model_id)
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="model_id_exists",
        )

    # If setting as default, clear other models' default flag of same type first
    if model_data.is_default:
        await crud.clear_default_models(db, model_data.model_type)

    # Create model
    new_model = await crud.create_model(db, model_data.model_dump())

    # Refresh model manager cache
    from app.core.model_manager import ModelManager

    await ModelManager.refresh()

    return model_to_info(new_model)


@api_router.post("/update", response_model=ModelInfo)
async def update_model(
    request: ModelUpdateRequest, db: AsyncSession = Depends(get_db)
) -> ModelInfo:
    """Update model configuration"""
    # Parse UUID from string
    try:
        model_uuid = uuid.UUID(request.id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid UUID format: '{request.id}'",
        )

    # Check if model exists
    existing = await crud.get_model_by_id(db, model_uuid)
    if not existing:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Model with id '{request.id}' not found",
        )

    # If setting as default, clear other models' default flag of same type first
    update_dict = request.model_dump(exclude_unset=True, exclude={"id"})
    if update_dict.get("is_default"):
        model_type = str(update_dict.get("model_type") or existing.model_type)
        await crud.clear_default_models(db, model_type)

    # Update model
    updated_model = await crud.update_model_by_id(db, model_uuid, update_dict)

    # Refresh model manager cache
    from app.core.model_manager import ModelManager

    await ModelManager.refresh()

    return model_to_info(updated_model)


@api_router.post("/delete", status_code=status.HTTP_204_NO_CONTENT)
async def delete_model(request: DeleteModelRequest, db: AsyncSession = Depends(get_db)):
    """Delete a model"""
    # Parse UUID from string
    try:
        model_uuid = uuid.UUID(request.id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid UUID format: '{request.id}'",
        )

    deleted = await crud.delete_model_by_id(db, model_uuid)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Model with id '{request.id}' not found",
        )

    # Refresh model manager cache
    from app.core.model_manager import ModelManager

    await ModelManager.refresh()

    return None


@api_router.post("/set-default", response_model=ModelInfo)
async def set_default_model(
    request: SetDefaultModelRequest, db: AsyncSession = Depends(get_db)
) -> ModelInfo:
    """Set default model for its type"""
    # Parse UUID from string
    try:
        model_uuid = uuid.UUID(request.id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid UUID format: '{request.id}'",
        )

    model = await crud.set_default_model_by_id(db, model_uuid)
    if not model:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Model with id '{request.id}' not found",
        )

    # Refresh model manager cache
    from app.core.model_manager import ModelManager

    await ModelManager.refresh()

    return model_to_info(model)


@api_router.post("/refresh", response_model=RefreshResponse)
async def refresh_models_cache() -> RefreshResponse:
    """
    Manually refresh the model manager cache.
    Call this after direct database modifications.
    """
    from app.core.model_manager import ModelManager

    await ModelManager.refresh()

    return RefreshResponse(
        success=True,
        message="Model cache refreshed successfully",
        models_count=len(ModelManager._models_cache),
    )
