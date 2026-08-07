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
from app.crud import provider_connection as connection_crud
from app.infra.llm import get_model_manager
from app.schemas.model import (
    ModelCapabilityStatus,
    ModelCreate,
    ModelInfo,
    ModelsResponse,
    ModelUpdateRequest,
    ModelValidationRequest,
    ThinkingModeStatus,
)
from app.schemas.provider import (
    ProviderConnectionCreate,
    ProviderConnectionInfo,
    ProviderConnectionsResponse,
    ProviderConnectionUpdate,
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
    connection = None
    create_data = model_data.model_dump()
    connection_id = create_data.get("connection_id")
    if connection_id:
        try:
            connection_uuid = uuid.UUID(str(connection_id))
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="invalid_connection_id",
            ) from exc
        connection = await connection_crud.get_connection(db, connection_uuid)
        if connection is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="connection_not_found",
            )
        existing = await model_crud.get_model_by_connection_model(
            db,
            connection.id,
            model_data.model_id,
        )
        create_data["connection_id"] = connection.id
        create_data["provider"] = connection.provider
    else:
        if not model_data.provider:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="provider_or_connection_required",
            )
        connection = await connection_crud.get_first_active_connection_for_provider(
            db,
            model_data.provider,
        )
        existing = await model_crud.get_model(db, model_data.model_id)
        create_data["provider"] = model_data.provider
        if connection:
            create_data["connection_id"] = connection.id

    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="model_id_exists",
        )

    create_data.pop("is_default", None)
    new_model = await model_crud.create_model(db, create_data)

    if model_data.is_default:
        new_model = await model_crud.set_default_model_by_id(db, new_model.id)

    await get_model_manager().refresh()
    return await _model_to_info(db, new_model)


@api_router.patch("/{model_id:uuid}", response_model=ModelInfo)
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
    if "connection_id" in update_dict and update_dict["connection_id"]:
        try:
            connection_uuid = uuid.UUID(str(update_dict["connection_id"]))
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="invalid_connection_id",
            ) from exc
        connection = await connection_crud.get_connection(db, connection_uuid)
        if connection is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="connection_not_found",
            )
        update_dict["connection_id"] = connection.id
        update_dict["provider"] = connection.provider

    updated_model = await model_crud.update_model_by_id(db, model_id, update_dict)

    if updated_model and update_dict.get("is_default"):
        updated_model = await model_crud.set_default_model_by_id(db, model_id)

    await get_model_manager().refresh()
    return await _model_to_info(db, updated_model)


@api_router.delete("/{model_id:uuid}", status_code=status.HTTP_204_NO_CONTENT)
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


@api_router.post("/{model_id:uuid}/validate", response_model=ModelCapabilityStatus)
async def validate_model(
    model_id: uuid.UUID,
    request: ModelValidationRequest | None = None,
    db: AsyncSession = Depends(get_db),
) -> ModelCapabilityStatus:
    """Run the configured model's modality-specific capability probe."""
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


@api_router.get(
    "/{model_id:uuid}/capabilities",
    response_model=ModelCapabilityStatus | None,
)
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
    provider_key = provider.provider
    return ProviderInfo(
        provider=provider_key,
        provider_key=provider_key,
        display_name=_provider_display_name(provider_key),
        adapter_type=provider_key,
        supports_connections=True,
        enabled=True,
        legacy=provider_key == "lmstudio",
        has_api_key=bool(provider.api_key),
        base_url=provider.base_url,
        is_openai_compatible=provider.is_openai_compatible,
        created_at=provider.created_at,
        updated_at=provider.updated_at,
    )


def _provider_display_name(provider_key: str) -> str:
    return {
        "dashscope": "DashScope",
        "openrouter": "OpenRouter",
        "openai-compatible": "OpenAI Compatible",
        "lmstudio": "LM Studio",
    }.get(provider_key, provider_key)


def _normalize_base_url(base_url: str | None) -> str | None:
    if base_url is None:
        return None
    normalized = base_url.strip()
    if not normalized:
        return None
    return normalized.rstrip("/")


def _connection_to_info(connection, model_count: int = 0) -> ProviderConnectionInfo:
    return ProviderConnectionInfo(
        connection_id=str(connection.id),
        provider_key=connection.provider,
        name=connection.name,
        preset_type=connection.preset_type,
        base_url=connection.base_url,
        has_api_key=bool(connection.api_key),
        enabled=bool(connection.is_active),
        model_count=model_count,
        extra_headers_json=connection.extra_headers_json or {},
        created_at=connection.created_at,
        updated_at=connection.updated_at,
    )


async def _model_to_info(db: AsyncSession, model) -> ModelInfo:
    info = ModelInfo.model_validate(model)
    info.model_uuid = str(model.id)
    info.provider_key = str(model.provider)
    info.provider_model_id = str(model.model_id)
    info.display_name = str(model.model_id)
    info.thinking_requested = bool(model.thinking)
    if model.connection_id:
        connection = await connection_crud.get_connection(db, model.connection_id)
        if connection:
            info.connection_name = connection.name
    return info


@api_router.get("/providers", response_model=ProvidersResponse)
async def get_all_providers(
    db: AsyncSession = Depends(get_db),
) -> ProvidersResponse:
    """Get all providers with their configuration status.

    Returns providers sorted alphabetically by name.
    """
    providers = [
        provider
        for provider in await provider_crud.get_all_providers(db)
        if provider.provider != "lmstudio"
    ]
    connection_counts = await connection_crud.get_provider_connection_counts(db)
    connections = await connection_crud.get_connections(db)
    connections_by_provider: dict[str, list] = {}
    for connection in connections:
        connections_by_provider.setdefault(connection.provider, []).append(connection)
    models = await model_crud.get_all_models(db, active_only=False)
    model_counts: dict[str, int] = {}
    for model in models:
        model_counts[str(model.provider)] = model_counts.get(str(model.provider), 0) + 1

    result: list[ProviderInfo] = []
    for provider in providers:
        info = _provider_to_info(provider)
        info.connection_count = connection_counts.get(provider.provider, 0)
        info.model_count = model_counts.get(provider.provider, 0)
        provider_connections = connections_by_provider.get(provider.provider, [])
        if provider_connections:
            info.has_api_key = any(bool(c.api_key) for c in provider_connections)
            info.base_url = next(
                (c.base_url for c in provider_connections if c.base_url),
                info.base_url,
            )
        result.append(info)
    return ProvidersResponse(providers=result)


@api_router.get("/connections", response_model=ProviderConnectionsResponse)
async def get_connections(
    provider_key: str | None = Query(
        None,
        description="Optional provider key filter, e.g. openai-compatible",
    ),
    db: AsyncSession = Depends(get_db),
) -> ProviderConnectionsResponse:
    """List provider connections."""
    connections = await connection_crud.get_connections(db, provider=provider_key)
    model_counts = await connection_crud.get_connection_model_counts(db)
    return ProviderConnectionsResponse(
        connections=[
            _connection_to_info(connection, model_counts.get(connection.id, 0))
            for connection in connections
        ]
    )


@api_router.post(
    "/connections",
    response_model=ProviderConnectionInfo,
    status_code=status.HTTP_201_CREATED,
)
async def create_connection(
    request: ProviderConnectionCreate,
    db: AsyncSession = Depends(get_db),
) -> ProviderConnectionInfo:
    """Create a concrete endpoint/account under a provider."""
    provider = await provider_crud.get_provider(db, request.provider_key)
    if not provider or request.provider_key == "lmstudio":
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="provider_not_found",
        )

    data = {
        "provider": request.provider_key,
        "name": request.name,
        "preset_type": request.preset_type,
        "api_key": encrypt_api_key(request.api_key or ""),
        "base_url": _normalize_base_url(request.base_url),
        "is_active": request.enabled,
        "extra_headers_json": request.extra_headers_json or {},
    }
    connection = await connection_crud.create_connection(db, data)
    await get_model_manager().refresh()
    return _connection_to_info(connection)


@api_router.patch(
    "/connections/{connection_id}",
    response_model=ProviderConnectionInfo,
)
async def update_connection(
    connection_id: uuid.UUID,
    request: ProviderConnectionUpdate,
    db: AsyncSession = Depends(get_db),
) -> ProviderConnectionInfo:
    """Update a provider connection."""
    update_data: dict = {}
    payload = request.model_dump(exclude_unset=True)

    if "name" in payload:
        update_data["name"] = request.name
    if "preset_type" in payload:
        update_data["preset_type"] = request.preset_type
    if "base_url" in payload:
        update_data["base_url"] = _normalize_base_url(request.base_url)
    if "enabled" in payload:
        update_data["is_active"] = request.enabled
    if "extra_headers_json" in payload:
        update_data["extra_headers_json"] = request.extra_headers_json or {}
    if request.clear_api_key:
        update_data["api_key"] = ""
    elif request.api_key is not None and request.api_key.strip():
        update_data["api_key"] = encrypt_api_key(request.api_key)

    if not update_data:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No fields to update",
        )

    connection = await connection_crud.update_connection(
        db,
        connection_id,
        update_data,
    )
    if not connection:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="connection_not_found",
        )

    await get_model_manager().refresh()
    model_counts = await connection_crud.get_connection_model_counts(db)
    return _connection_to_info(connection, model_counts.get(connection.id, 0))


@api_router.delete(
    "/connections/{connection_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_connection(
    connection_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> None:
    """Delete a provider connection and its configured models."""
    deleted = await connection_crud.delete_connection(db, connection_id)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="connection_not_found",
        )

    await get_model_manager().refresh()


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
    """Return the default model's configured mode (legacy response shape)."""
    return ThinkingModeStatus(
        available=get_model_manager().is_thinking_mode_configured()
    )
