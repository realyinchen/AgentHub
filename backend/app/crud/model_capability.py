import uuid
from typing import Iterable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.model_capability import ModelCapabilityCheck


async def create_capability_check(
    db: AsyncSession,
    data: dict,
) -> ModelCapabilityCheck:
    """Persist a model capability check result."""
    check = ModelCapabilityCheck(**data)
    db.add(check)
    await db.flush()
    await db.refresh(check)
    return check


async def get_latest_capability_check(
    db: AsyncSession,
    model_id: uuid.UUID,
) -> ModelCapabilityCheck | None:
    """Return the latest capability check for one model."""
    result = await db.execute(
        select(ModelCapabilityCheck)
        .where(ModelCapabilityCheck.model_id == model_id)
        .order_by(ModelCapabilityCheck.checked_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def get_latest_capability_checks(
    db: AsyncSession,
    model_ids: Iterable[uuid.UUID],
) -> dict[uuid.UUID, ModelCapabilityCheck]:
    """Return latest capability checks keyed by model UUID."""
    ids = list(model_ids)
    if not ids:
        return {}

    result = await db.execute(
        select(ModelCapabilityCheck)
        .where(ModelCapabilityCheck.model_id.in_(ids))
        .order_by(ModelCapabilityCheck.model_id, ModelCapabilityCheck.checked_at.desc())
    )

    latest: dict[uuid.UUID, ModelCapabilityCheck] = {}
    for check in result.scalars().all():
        latest.setdefault(check.model_id, check)
    return latest
