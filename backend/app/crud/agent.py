from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional

from app.models.agent import Agent


# ==================== Agent CRUD ====================


async def create_agent(db: AsyncSession, agent_data: dict) -> Agent:
    """Create a new agent"""
    db_obj = Agent(**agent_data)
    db.add(db_obj)
    await db.flush()
    await db.refresh(db_obj)
    return db_obj


async def list_agents(
    db: AsyncSession,
    active_only: bool = True,
    limit: int = 20,
    offset: int = 0,
) -> list[Agent]:
    """List agents with optional filtering and pagination"""
    stmt = select(Agent)

    if active_only:
        stmt = stmt.where(Agent.is_active.is_(True))

    stmt = stmt.offset(offset).limit(limit).order_by(Agent.created_at.desc())

    result = await db.execute(stmt)
    return list(result.scalars().all())


async def get_agent(
    db: AsyncSession, agent_id: str, active_only: bool = True
) -> Optional[Agent]:
    """Get a single agent by agent_id"""
    stmt = select(Agent).where(Agent.agent_id == agent_id)

    if active_only:
        stmt = stmt.where(Agent.is_active.is_(True))

    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def update_agent(
    db: AsyncSession, agent_id: str, update_data: dict
) -> Optional[Agent]:
    """Update an agent by agent_id (partial update)"""
    stmt = (
        update(Agent)
        .where(Agent.agent_id == agent_id)
        .values(**update_data)
        .returning(Agent)
    )

    result = await db.execute(stmt)
    await db.flush()
    return result.scalar_one_or_none()


async def soft_delete_agent(db: AsyncSession, agent_id: str) -> bool:
    """Soft delete an agent (set is_active = False)"""
    stmt = (
        update(Agent)
        .where(Agent.agent_id == agent_id)
        .where(Agent.is_active.is_(True))
        .values(is_active=False)
        .returning(Agent.agent_id)
    )

    result = await db.execute(stmt)
    await db.flush()
    return bool(result.scalar_one_or_none())
