import os
import uuid
from typing import Optional
from fastapi import APIRouter, HTTPException, status, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.dependencies import get_db
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

    # Create model
    new_model = await crud.create_model(db, model_data.model_dump())

    # If setting as default, use atomic CASE statement to set as default and clear others
    if model_data.is_default:
        new_model = await crud.set_default_model_by_model_id(
            db, str(new_model.model_id)
        )

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

    update_dict = request.model_dump(exclude_unset=True, exclude={"id"})

    # Update model
    updated_model = await crud.update_model_by_id(db, model_uuid, update_dict)

    # If setting as default, use atomic CASE statement to set as default and clear others
    if updated_model and update_dict.get("is_default"):
        updated_model = await crud.set_default_model_by_id(db, model_uuid)

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
        models_count=ModelManager.get_models_count(),
    )


@api_router.get("/health/{model_id}")
async def check_model_health(model_id: str, db: AsyncSession = Depends(get_db)):
    """
    Check connectivity and health status for a specific model.

    Performs a lightweight test request to verify:
    1. API key is valid
    2. Model is accessible
    3. Provider endpoint is reachable

    Returns health status with latency and error details if applicable.
    """
    import time
    import logging
    from litellm import acompletion

    logger = logging.getLogger(__name__)

    # Get model from database
    model = await crud.get_model(db, model_id)
    if not model:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Model '{model_id}' not found",
        )

    # Get provider configuration (API key and base URL)
    from app.crud import provider as provider_crud

    provider_config = await provider_crud.get_provider(db, model.provider)

    if not provider_config or not provider_config.api_key:
        return {
            "model_id": model_id,
            "provider": model.provider,
            "status": "unconfigured",
            "latency_ms": None,
            "error": "No API key configured for provider",
        }

    # Build LiteLLM parameters
    litellm_params = {
        "model": model_id,
        "api_key": provider_config.api_key,
        "max_tokens": 5,  # Minimal token count for health check
        "timeout": 10,  # 10 second timeout
    }

    if provider_config.base_url:
        litellm_params["api_base"] = provider_config.base_url

    start_time = time.perf_counter()

    try:
        # Perform a minimal completion request
        response = await acompletion(
            messages=[{"role": "user", "content": "Hi"}],
            **litellm_params,
        )

        latency_ms = (time.perf_counter() - start_time) * 1000

        # Extract token usage if available
        usage = None
        # Access usage attribute safely - LiteLLM response has usage attribute
        usage_obj = getattr(response, "usage", None)
        if usage_obj:
            usage = {
                "input_tokens": getattr(usage_obj, "prompt_tokens", 0),
                "output_tokens": getattr(usage_obj, "completion_tokens", 0),
                "total_tokens": getattr(usage_obj, "total_tokens", 0),
            }

        return {
            "model_id": model_id,
            "provider": model.provider,
            "status": "healthy",
            "latency_ms": round(latency_ms, 2),
            "usage": usage,
        }

    except Exception as e:
        latency_ms = (time.perf_counter() - start_time) * 1000
        error_str = str(e)

        # Classify error type
        error_type = "unknown"
        error_lower = error_str.lower()
        if "rate limit" in error_lower or "429" in error_lower:
            error_type = "rate_limit_exceeded"
        elif (
            "forbidden" in error_lower
            or "403" in error_lower
            or "unauthorized" in error_lower
        ):
            error_type = "invalid_credentials"
        elif "timeout" in error_lower:
            error_type = "timeout"
        elif "not found" in error_lower or "404" in error_lower:
            error_type = "model_not_found"
        elif "quota" in error_lower or "exhausted" in error_lower:
            error_type = "quota_exhausted"

        logger.warning(
            f"Health check failed for {model_id}: {error_type} - {error_str[:200]}"
        )

        return {
            "model_id": model_id,
            "provider": model.provider,
            "status": "unhealthy",
            "latency_ms": round(latency_ms, 2),
            "error": error_str[:500],
            "error_type": error_type,
        }


@api_router.get("/health")
async def check_all_models_health(db: AsyncSession = Depends(get_db)):
    """
    Check health status for all configured models.

    Returns health status, latency, and token usage for each active model.
    This may take a few seconds depending on the number of models.
    """
    import asyncio

    models = await crud.get_models_with_provider_config(db)

    # Only check active models
    active_models = [m for m in models if m.is_active]

    # Run health checks concurrently for all models
    tasks = []
    for model in active_models:
        tasks.append(check_model_health(model.model_id, db))

    results = await asyncio.gather(*tasks, return_exceptions=True)

    # Process results
    health_results = []
    for i, result in enumerate(results):
        model_id = active_models[i].model_id
        if isinstance(result, Exception):
            health_results.append(
                {
                    "model_id": model_id,
                    "provider": active_models[i].provider,
                    "status": "error",
                    "latency_ms": None,
                    "error": str(result)[:200],
                }
            )
        else:
            health_results.append(result)

    # Calculate summary stats
    total = len(health_results)
    healthy = sum(1 for r in health_results if r["status"] == "healthy")
    unhealthy = sum(1 for r in health_results if r["status"] == "unhealthy")
    unconfigured = sum(1 for r in health_results if r["status"] == "unconfigured")

    return {
        "summary": {
            "total": total,
            "healthy": healthy,
            "unhealthy": unhealthy,
            "unconfigured": unconfigured,
        },
        "models": health_results,
    }
