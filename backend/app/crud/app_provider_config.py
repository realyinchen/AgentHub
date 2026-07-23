from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.app_provider_config import AppProviderConfigRecord


async def get_app_provider_configs(
    db: AsyncSession,
    *,
    scope: str | None = None,
) -> list[AppProviderConfigRecord]:
    stmt = select(AppProviderConfigRecord)
    if scope:
        stmt = stmt.where(AppProviderConfigRecord.scope == scope)
    stmt = stmt.order_by(
        AppProviderConfigRecord.provider_type,
        AppProviderConfigRecord.provider_key,
        AppProviderConfigRecord.scope,
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def get_app_provider_config(
    db: AsyncSession,
    provider_key: str,
    *,
    scope: str = "global",
) -> AppProviderConfigRecord | None:
    result = await db.execute(
        select(AppProviderConfigRecord).where(
            AppProviderConfigRecord.provider_key == provider_key,
            AppProviderConfigRecord.scope == scope,
        )
    )
    return result.scalar_one_or_none()


async def update_app_provider_config(
    db: AsyncSession,
    provider_key: str,
    data: dict,
    *,
    scope: str = "global",
) -> AppProviderConfigRecord | None:
    record = await get_app_provider_config(db, provider_key, scope=scope)
    if record is None:
        return None

    for key, value in data.items():
        setattr(record, key, value)

    await db.flush()
    await db.refresh(record)
    return record


async def create_app_provider_config(
    db: AsyncSession,
    data: dict,
) -> AppProviderConfigRecord:
    record = AppProviderConfigRecord(**data)
    db.add(record)
    await db.flush()
    await db.refresh(record)
    return record
