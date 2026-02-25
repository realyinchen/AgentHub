from fastapi import APIRouter, HTTPException, status, Depends, Query
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List

from app.database import adb_manager
from app.models.agent import Agent
from app.schemas.agent import AgentCreate, AgentUpdate, AgentInDB

api_router = APIRouter(prefix="/agents", tags=["Agent"])


async def get_db():
    """Dependency to provide async session"""
    async with adb_manager.session() as session:
        yield session


@api_router.post("/", response_model=AgentInDB, status_code=status.HTTP_201_CREATED)
async def create_agent(
    agent_in: AgentCreate, db: AsyncSession = Depends(get_db)
) -> AgentInDB:
    # Convert Pydantic to dict, exclude unset fields
    create_data = agent_in.model_dump(exclude_unset=True)

    db_obj = Agent(**create_data)

    db.add(db_obj)

    return AgentInDB.model_validate(db_obj)


@api_router.get("/", response_model=List[AgentInDB])
async def list_agents(
    active_only: bool = Query(True, description="Only show active agents"),
    limit: int = Query(20, ge=1, le=100, description="Max number of agents to return"),
    offset: int = Query(0, ge=0, description="Number of agents to skip"),
    db: AsyncSession = Depends(get_db),
) -> List[AgentInDB]:
    """
    List agents with optional filtering and pagination.
    """
    stmt = select(Agent)

    if active_only:
        stmt = stmt.where(Agent.is_active.is_(True))

    stmt = stmt.offset(offset).limit(limit).order_by(Agent.created_at.desc())

    result = await db.execute(stmt)
    agents = result.scalars().all()

    return [AgentInDB.model_validate(agent) for agent in agents]


@api_router.get("/{agent_id}", response_model=AgentInDB)
async def get_agent(
    agent_id: str,
    active_only: bool = Query(True, description="Only return active agents"),
    db: AsyncSession = Depends(get_db),
) -> AgentInDB:
    """
    Get a single agent by ID.
    """
    stmt = select(Agent).where(Agent.agent_id == agent_id)

    if active_only:
        stmt = stmt.where(Agent.is_active.is_(True))

    result = await db.execute(stmt)
    agent = result.scalar_one_or_none()

    if not agent:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found or inactive"
        )

    return AgentInDB.model_validate(agent)


@api_router.patch("/{agent_id}", response_model=AgentInDB)
async def update_agent(
    agent_id: str, agent_update: AgentUpdate, db: AsyncSession = Depends(get_db)
) -> AgentInDB:
    """
    Update an existing agent (partial update supported).
    """
    if not agent_update.model_dump(exclude_unset=True):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No fields provided to update",
        )

    stmt = (
        update(Agent)
        .where(Agent.agent_id == agent_id)
        .values(**agent_update.model_dump(exclude_unset=True))
        .returning(Agent)
    )

    result = await db.execute(stmt)
    updated = result.scalar_one_or_none()

    if not updated:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found"
        )

    return AgentInDB.model_validate(updated)


@api_router.delete("/{agent_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_agent(agent_id: str, db: AsyncSession = Depends(get_db)):
    """
    Soft delete an agent (set is_active = False).
    """
    stmt = (
        update(Agent)
        .where(Agent.agent_id == agent_id)
        .where(Agent.is_active.is_(True))  # Only deactivate active agents
        .values(is_active=False)
        .returning(Agent.agent_id)
    )

    result = await db.execute(stmt)
    deactivated = result.scalar_one_or_none()

    if not deactivated:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Agent not found or already inactive",
        )

    return None
