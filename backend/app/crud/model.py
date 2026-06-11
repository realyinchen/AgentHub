import uuid

from sqlalchemy import select, update, case, or_
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional

from app.models.model import Model
from app.schemas.model import ModelCapabilityStatus, ModelInfo, ModelsResponse


# ==================== Model CRUD ====================


async def get_model_by_id(db: AsyncSession, id: uuid.UUID) -> Optional[Model]:
    """Get a single model by UUID primary key"""
    result = await db.execute(select(Model).where(Model.id == id))
    return result.scalar_one_or_none()


async def get_model(db: AsyncSession, model_id: str) -> Optional[Model]:
    """Get a single model by model_id string"""
    result = await db.execute(select(Model).where(Model.model_id == model_id))
    return result.scalar_one_or_none()


async def get_all_models(db: AsyncSession, active_only: bool = True) -> list[Model]:
    """Get all models"""
    stmt = select(Model)
    if active_only:
        stmt = stmt.where(Model.is_active.is_(True))
    stmt = stmt.order_by(Model.provider, Model.model_id)

    result = await db.execute(stmt)
    return list(result.scalars().all())


async def get_models_by_type(
    db: AsyncSession, model_type: str, active_only: bool = True
) -> list[Model]:
    """Get models by type"""
    stmt = select(Model).where(Model.model_type == model_type)
    if active_only:
        stmt = stmt.where(Model.is_active.is_(True))
    stmt = stmt.order_by(Model.provider, Model.model_id)

    result = await db.execute(stmt)
    return list(result.scalars().all())


async def get_models_with_provider_config(db: AsyncSession) -> list[Model]:
    """Get all active models with their provider configured"""
    from app.models.provider import Provider

    result = await db.execute(
        select(Model)
        .join(Provider, Model.provider == Provider.provider)
        .where(
            Model.is_active.is_(True),
            or_(
                Provider.api_key != "",
                (
                    Provider.is_openai_compatible.is_(True)
                    & (Provider.provider != "openrouter")
                    & Provider.base_url.is_not(None)
                ),
            ),
        )
        .order_by(Model.provider, Model.model_id)
    )
    return list(result.scalars().all())


async def create_model(db: AsyncSession, model_data: dict) -> Model:
    """Create a new model"""
    new_model = Model(**model_data)
    db.add(new_model)
    await db.flush()
    await db.refresh(new_model)
    return new_model


async def update_model_by_id(
    db: AsyncSession, id: uuid.UUID, model_data: dict
) -> Optional[Model]:
    """Update a model by UUID primary key

    Note: model_data should be generated using model_dump(exclude_unset=True)
    to ensure only fields explicitly set by the caller are updated.
    """
    model = await get_model_by_id(db, id)
    if not model:
        return None

    for key, value in model_data.items():
        setattr(model, key, value)

    await db.flush()
    await db.refresh(model)
    return model


async def delete_model_by_id(db: AsyncSession, id: uuid.UUID) -> bool:
    """Delete a model by UUID primary key"""
    model = await get_model_by_id(db, id)
    if not model:
        return False

    await db.delete(model)
    await db.flush()
    return True


async def get_default_model_by_type(
    db: AsyncSession, model_type: str
) -> Optional[Model]:
    """Get the default model for a specific type"""
    result = await db.execute(
        select(Model).where(
            Model.model_type == model_type,
            Model.is_default.is_(True),
            Model.is_active.is_(True),
        )
    )
    return result.scalar_one_or_none()


async def set_default_model_by_id(db: AsyncSession, id: uuid.UUID) -> Optional[Model]:
    """Set default model for its model_type by UUID primary key (atomic: single SQL statement)"""
    model = await get_model_by_id(db, id)
    if not model:
        return None

    # Atomic: set target as default and clear others' default in a single SQL statement
    await db.execute(
        update(Model)
        .where(Model.model_type == model.model_type)
        .values(
            is_default=case(
                (Model.id == id, True),
                else_=False,
            )
        )
    )
    await db.flush()
    await db.refresh(model)
    return model


async def set_default_model_by_model_id(
    db: AsyncSession, model_id: str
) -> Optional[Model]:
    """Set default model for its model_type by model_id string (atomic CASE)

    Single SQL statement that both sets the target as default AND clears
    all other models' default flag in the same model_type.
    """
    model = await get_model(db, model_id)
    if not model:
        return None

    # Atomic: set target as default and clear others' default in a single SQL statement
    model_uuid = model.id
    await db.execute(
        update(Model)
        .where(Model.model_type == model.model_type)
        .values(
            is_default=case(
                (Model.id == model_uuid, True),
                else_=False,
            )
        )
    )
    await db.flush()
    await db.refresh(model)
    return model


async def deactivate_model(db: AsyncSession, model_id: str) -> Optional[Model]:
    """Deactivate a model by model_id string

    Mark a model as inactive when it fails (e.g., rate limit exceeded, quota exhausted, permission errors).
    This prevents it from being selected in future requests until manually reactivated.
    """
    model = await get_model(db, model_id)
    if not model:
        return None

    model.is_active = False
    await db.flush()
    await db.refresh(model)
    return model


# ==================== Response Builders ====================


def get_first_model_by_type(models: list[Model], model_type: str) -> Optional[str]:
    """Get the first model of a specific type from a sorted list.

    Models are already sorted by provider (alphabetically), then by model_id.
    Returns the model_id of the first matching model, or None if not found.
    """
    for model in models:
        if model.model_type == model_type:
            return model.model_id
    return None


def build_models_response(
    models: list[Model],
    capabilities: dict[uuid.UUID, object] | None = None,
) -> ModelsResponse:
    """Build ModelsResponse from model list.

    Optimized to extract default models from the list instead of additional
    DB queries. Default model selection logic:
    - If a model has is_default=True, use that
    - Otherwise, use the first model of that type (sorted alphabetically by provider)
    """
    capability_map = capabilities or {}
    model_infos: list[ModelInfo] = []
    for m in models:
        info = ModelInfo.model_validate(m)
        capability = capability_map.get(m.id)
        if capability:
            info.capability = ModelCapabilityStatus.model_validate(capability)
        model_infos.append(info)

    default_llm_id: Optional[str] = None
    default_vlm_id: Optional[str] = None
    default_embedding_id: Optional[str] = None

    for m in models:
        if getattr(m, "is_default", False):
            model_type = getattr(m, "model_type", "llm")
            if model_type == "llm" and default_llm_id is None:
                default_llm_id = str(m.model_id)
            elif model_type == "vlm" and default_vlm_id is None:
                default_vlm_id = str(m.model_id)
            elif model_type == "embedding" and default_embedding_id is None:
                default_embedding_id = str(m.model_id)

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


async def get_models_response(
    db: AsyncSession,
    active_only: bool = True,
) -> ModelsResponse:
    """Get models and build response in one call.

    Convenience function that combines get_all_models and build_models_response.
    """
    models = await get_all_models(db, active_only=active_only)
    from app.crud import model_capability as capability_crud

    capabilities = await capability_crud.get_latest_capability_checks(
        db, [m.id for m in models]
    )
    return build_models_response(models, capabilities=capabilities)
