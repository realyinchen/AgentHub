from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional

from app.models.provider import Provider


# ==================== Provider CRUD ====================


async def get_provider(db: AsyncSession, provider: str) -> Optional[Provider]:
    """Get a provider by name"""
    result = await db.execute(select(Provider).where(Provider.provider == provider))
    return result.scalar_one_or_none()


async def get_all_providers(db: AsyncSession) -> list[Provider]:
    """Get all providers"""
    result = await db.execute(select(Provider).order_by(Provider.provider))
    return list(result.scalars().all())


async def update_provider(
    db: AsyncSession, provider: str, provider_data: dict
) -> Optional[Provider]:
    """Update a provider configuration"""
    provider_obj = await get_provider(db, provider)
    if not provider_obj:
        return None

    for key, value in provider_data.items():
        if value is not None:
            setattr(provider_obj, key, value)

    await db.commit()
    await db.refresh(provider_obj)
    return provider_obj
