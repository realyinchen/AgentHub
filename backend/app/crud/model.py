from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional

from app.models.model import Model


# ==================== Model CRUD ====================


async def get_model(db: AsyncSession, model_id: str) -> Optional[Model]:
    """Get a single model by ID"""
    result = await db.execute(select(Model).where(Model.model_id == model_id))
    return result.scalar_one_or_none()


async def get_model_by_name(db: AsyncSession, model_name: str) -> Optional[Model]:
    """Get a single model by name"""
    result = await db.execute(select(Model).where(Model.model_name == model_name))
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


async def get_models_with_api_key(db: AsyncSession) -> list[Model]:
    """Get all active models with API key configured"""
    result = await db.execute(
        select(Model)
        .where(
            Model.is_active.is_(True),
            Model.api_key != "",
        )
        .order_by(Model.provider, Model.model_id)
    )
    return list(result.scalars().all())


async def create_model(db: AsyncSession, model_data: dict) -> Model:
    """Create a new model"""
    new_model = Model(**model_data)
    db.add(new_model)
    await db.commit()
    await db.refresh(new_model)
    return new_model


async def update_model(
    db: AsyncSession, model_id: str, model_data: dict
) -> Optional[Model]:
    """Update a model"""
    model = await get_model(db, model_id)
    if not model:
        return None

    for key, value in model_data.items():
        if value is not None:
            setattr(model, key, value)

    await db.commit()
    await db.refresh(model)
    return model


async def delete_model(db: AsyncSession, model_id: str) -> bool:
    """Delete a model"""
    model = await get_model(db, model_id)
    if not model:
        return False

    await db.delete(model)
    await db.commit()
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


async def set_default_model(db: AsyncSession, model_id: str) -> Optional[Model]:
    """Set default model for its model_type (clears other models' default flag of same type)"""
    model = await get_model(db, model_id)
    if not model:
        return None

    # Clear other models' default flag of the same type
    await db.execute(
        update(Model)
        .where(Model.model_type == model.model_type)
        .values(is_default=False)
    )

    # Set this model as default
    setattr(model, "is_default", True)

    await db.commit()
    await db.refresh(model)
    return model


async def clear_default_models(db: AsyncSession, model_type: str):
    """Clear all default model flags for a specific type"""
    await db.execute(
        update(Model).where(Model.model_type == model_type).values(is_default=False)
    )
    await db.commit()
