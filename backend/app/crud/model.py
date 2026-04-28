import uuid

from sqlalchemy import select, update, case
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional

from app.models.model import Model


# ==================== Model CRUD ====================


async def get_model_by_id(db: AsyncSession, id: uuid.UUID) -> Optional[Model]:
    """Get a single model by UUID primary key"""
    result = await db.execute(select(Model).where(Model.id == id))
    return result.scalar_one_or_none()


async def get_model(db: AsyncSession, model_id: str) -> Optional[Model]:
    """Get a single model by model_id string"""
    result = await db.execute(select(Model).where(Model.model_id == model_id))
    return result.scalar_one_or_none()


async def get_model_by_name(db: AsyncSession, model_name: str) -> Optional[Model]:
    """Get a single model by name"""
    result = await db.execute(select(Model).where(Model.model_id == model_name))
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
            Provider.api_key != "",
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


async def update_model(
    db: AsyncSession, model_id: str, model_data: dict
) -> Optional[Model]:
    """Update a model by model_id string (legacy)

    Note: model_data should be generated using model_dump(exclude_unset=True)
    to ensure only fields explicitly set by the caller are updated.
    """
    model = await get_model(db, model_id)
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


async def delete_model(db: AsyncSession, model_id: str) -> bool:
    """Delete a model by model_id string (legacy)"""
    model = await get_model(db, model_id)
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


async def set_default_model(db: AsyncSession, model_id: str) -> Optional[Model]:
    """Set default model for its model_type by model_id string (atomic)

    Alias for set_default_model_by_model_id for backwards compatibility.
    """
    return await set_default_model_by_model_id(db, model_id)


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
