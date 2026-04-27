from fastapi import APIRouter, HTTPException, status, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List

from app.schemas.agent import AgentCreate, AgentUpdate, AgentInDB
from app.core.rate_limiter import limiter, RateLimits
from app.api.v1.dependencies import get_db
from app.crud import agent as agent_crud

api_router = APIRouter(prefix="/agents", tags=["Agent"])


@api_router.post("/", response_model=AgentInDB, status_code=status.HTTP_201_CREATED)
async def create_agent(
    agent_in: AgentCreate, db: AsyncSession = Depends(get_db)
) -> AgentInDB:
    create_data = agent_in.model_dump(exclude_unset=True)
    db_obj = await agent_crud.create_agent(db, create_data)
    return AgentInDB.model_validate(db_obj)


@api_router.get("/", response_model=List[AgentInDB])
@limiter.limit(RateLimits.LIST_AGENTS)
async def list_agents(
    request: Request,
    active_only: bool = Query(True, description="Only show active agents"),
    limit: int = Query(20, ge=1, le=100, description="Max number of agents to return"),
    offset: int = Query(0, ge=0, description="Number of agents to skip"),
    db: AsyncSession = Depends(get_db),
) -> List[AgentInDB]:
    """List agents with optional filtering and pagination."""
    agents = await agent_crud.list_agents(
        db, active_only=active_only, limit=limit, offset=offset
    )
    return [AgentInDB.model_validate(agent) for agent in agents]


@api_router.get("/{agent_id}", response_model=AgentInDB)
async def get_agent(
    agent_id: str,
    active_only: bool = Query(True, description="Only return active agents"),
    db: AsyncSession = Depends(get_db),
) -> AgentInDB:
    """Get a single agent by ID."""
    agent = await agent_crud.get_agent(db, agent_id, active_only=active_only)

    if not agent:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found or inactive"
        )

    return AgentInDB.model_validate(agent)


@api_router.patch("/{agent_id}", response_model=AgentInDB)
async def update_agent(
    agent_id: str, agent_update: AgentUpdate, db: AsyncSession = Depends(get_db)
) -> AgentInDB:
    """Update an existing agent (partial update supported)."""
    if not agent_update.model_dump(exclude_unset=True):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No fields provided to update",
        )

    updated = await agent_crud.update_agent(
        db, agent_id, agent_update.model_dump(exclude_unset=True)
    )

    if not updated:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found"
        )

    return AgentInDB.model_validate(updated)


@api_router.delete("/{agent_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_agent(agent_id: str, db: AsyncSession = Depends(get_db)):
    """Soft delete an agent (set is_active = False)."""
    deactivated = await agent_crud.soft_delete_agent(db, agent_id)

    if not deactivated:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Agent not found or already inactive",
        )

    return None
