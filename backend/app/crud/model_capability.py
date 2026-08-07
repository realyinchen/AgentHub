import uuid
from typing import Iterable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.model_capability import ModelCapabilityCheck


async def create_capability_check(
    db: AsyncSession,
    data: dict,
) -> ModelCapabilityCheck:
    """Persist canonical probe fields while retaining the legacy table shape."""

    payload = dict(data)
    raw_summary = dict(payload.pop("raw_summary", {}) or {})
    for field in (
        "probe_kind",
        "probe_ok",
        "embedding_dimensions",
        "error_category",
    ):
        if field in payload:
            value = payload.pop(field)
            if value is not None:
                raw_summary[field] = value

    if "chat_ok" not in payload:
        payload["chat_ok"] = bool(raw_summary.get("probe_ok", False))
    raw_summary.setdefault("probe_kind", "chat")
    raw_summary.setdefault("probe_ok", bool(payload["chat_ok"]))
    payload["raw_summary"] = raw_summary

    check = ModelCapabilityCheck(**payload)
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
        .order_by(
            ModelCapabilityCheck.model_id,
            ModelCapabilityCheck.checked_at.desc(),
        )
    )

    latest: dict[uuid.UUID, ModelCapabilityCheck] = {}
    for check in result.scalars().all():
        latest.setdefault(check.model_id, check)
    return latest
