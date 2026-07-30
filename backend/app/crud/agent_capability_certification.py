from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent_capability_certification import (
    AgentCapabilityCertification,
)


async def create_certification(
    db: AsyncSession,
    data: dict,
) -> AgentCapabilityCertification:
    certification = AgentCapabilityCertification(**dict(data))
    db.add(certification)
    await db.flush()
    await db.refresh(certification)
    return certification


async def get_latest_certification(
    db: AsyncSession,
    model_id: uuid.UUID,
    *,
    configuration_fingerprint: str | None = None,
    contract_version: str | None = None,
    controller_fingerprint: str | None = None,
    source_commit_sha: str | None = None,
) -> AgentCapabilityCertification | None:
    query = select(AgentCapabilityCertification).where(
        AgentCapabilityCertification.model_id == model_id
    )
    if configuration_fingerprint is not None:
        query = query.where(
            AgentCapabilityCertification.configuration_fingerprint
            == configuration_fingerprint
        )
    if contract_version is not None:
        query = query.where(
            AgentCapabilityCertification.contract_version == contract_version
        )
    if controller_fingerprint is not None:
        query = query.where(
            AgentCapabilityCertification.controller_fingerprint
            == controller_fingerprint
        )
    if source_commit_sha is not None:
        query = query.where(
            AgentCapabilityCertification.source_commit_sha
            == source_commit_sha
        )
    result = await db.execute(
        query.order_by(AgentCapabilityCertification.checked_at.desc()).limit(1)
    )
    return result.scalar_one_or_none()


__all__ = ["create_certification", "get_latest_certification"]
