import uuid
from typing import Optional

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.model import Model
from app.models.provider_connection import ProviderConnection


async def get_connection(
    db: AsyncSession, connection_id: uuid.UUID
) -> Optional[ProviderConnection]:
    result = await db.execute(
        select(ProviderConnection).where(ProviderConnection.id == connection_id)
    )
    return result.scalar_one_or_none()


async def get_connections(
    db: AsyncSession,
    provider: str | None = None,
    active_only: bool = False,
) -> list[ProviderConnection]:
    stmt = select(ProviderConnection)
    if provider:
        stmt = stmt.where(ProviderConnection.provider == provider)
    if active_only:
        stmt = stmt.where(ProviderConnection.is_active.is_(True))
    stmt = stmt.order_by(ProviderConnection.provider, ProviderConnection.name)
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def get_connection_model_counts(
    db: AsyncSession,
) -> dict[uuid.UUID, int]:
    result = await db.execute(
        select(Model.connection_id, func.count(Model.id))
        .where(Model.connection_id.is_not(None))
        .group_by(Model.connection_id)
    )
    return {
        connection_id: int(count)
        for connection_id, count in result.all()
        if connection_id is not None
    }


async def get_provider_connection_counts(db: AsyncSession) -> dict[str, int]:
    result = await db.execute(
        select(ProviderConnection.provider, func.count(ProviderConnection.id)).group_by(
            ProviderConnection.provider
        )
    )
    return {provider: int(count) for provider, count in result.all()}


async def create_connection(
    db: AsyncSession,
    data: dict,
) -> ProviderConnection:
    connection = ProviderConnection(**data)
    db.add(connection)
    await db.flush()
    await db.refresh(connection)
    return connection


async def update_connection(
    db: AsyncSession,
    connection_id: uuid.UUID,
    data: dict,
) -> Optional[ProviderConnection]:
    connection = await get_connection(db, connection_id)
    if not connection:
        return None

    for key, value in data.items():
        setattr(connection, key, value)

    await db.flush()
    await db.refresh(connection)
    return connection


async def delete_connection(
    db: AsyncSession,
    connection_id: uuid.UUID,
) -> bool:
    connection = await get_connection(db, connection_id)
    if not connection:
        return False

    result = await db.execute(
        select(Model).where(Model.connection_id == connection_id)
    )
    for model in result.scalars().all():
        await db.delete(model)

    await db.delete(connection)
    await db.flush()
    return True


async def get_first_active_connection_for_provider(
    db: AsyncSession,
    provider: str,
) -> Optional[ProviderConnection]:
    result = await db.execute(
        select(ProviderConnection)
        .where(
            ProviderConnection.provider == provider,
            ProviderConnection.is_active.is_(True),
        )
        .order_by(ProviderConnection.created_at, ProviderConnection.name)
        .limit(1)
    )
    return result.scalar_one_or_none()


async def assign_provider_models_to_connection(
    db: AsyncSession,
    provider: str,
    connection_id: uuid.UUID,
) -> None:
    await db.execute(
        update(Model)
        .where(Model.provider == provider, Model.connection_id.is_(None))
        .values(connection_id=connection_id)
    )
    await db.flush()
