"""Agent Discovery API (DB-driven, memory-cached).

Serves agent metadata from in-memory dict (zero DB query).  The registry is
populated at startup from the ``agents`` DB table and refreshed on any
agent-table mutation (create / update / delete).

- GET /agents: List all active agents
- PATCH /agents/{agent_id}: Update an agent row (is_active=False → offline)
"""

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.registry import get_metadata, list_metadata, reload_agent
from app.api.v1.dependencies import get_db
from app.models.agent import Agent as AgentModel
from app.schemas.agent import AgentListResponse, AgentResponse, AgentUpdate

logger = logging.getLogger(__name__)

api_router = APIRouter(prefix="/agents", tags=["Agent"])


# ── Discovery API ───────────────────────────────────────────────────────


@api_router.get("/", response_model=AgentListResponse)
async def list_agents() -> AgentListResponse:
    """
    List all active agents.

    Reads directly from memory cache — zero DB query, sub-millisecond.
    """
    rows = list(list_metadata())
    return AgentListResponse(
        agents=[AgentResponse.model_validate(r) for r in rows],
        total=len(rows),
        timestamp=datetime.now(timezone.utc),
    )


@api_router.get("/{agent_id}", response_model=AgentResponse)
async def get_agent_detail(agent_id: str) -> AgentResponse:
    """
    Get metadata for a single agent.

    Raises:
        404: Agent not found or not active
    """
    row = get_metadata(agent_id)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Agent '{agent_id}' not found",
        )
    return AgentResponse.model_validate(row)


# ── Admin API ───────────────────────────────────────────────────────────


@api_router.patch("/{agent_id}", response_model=AgentResponse)
async def update_agent(
    agent_id: str,
    body: AgentUpdate,
    db: AsyncSession = Depends(get_db),
) -> AgentResponse:
    """
    Update an agent row in DB, then refresh the agent cache.

    Set ``is_active=false`` to take an agent offline — it will be removed
    from the memory cache on refresh.
    """
    row = await db.get(AgentModel, agent_id)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Agent '{agent_id}' not found",
        )

    if body.description is not None:
        row.description = body.description
    if body.is_active is not None:
        row.is_active = body.is_active

    # Flush to push UPDATE to the DB so refresh() can read server-side fields,
    # but defer commit to the get_db()/db.session() context manager
    # (project rule: business code must not commit/rollback directly).
    await db.flush()
    await db.refresh(row)

    await reload_agent(agent_id)
    logger.info(
        "Agent updated and registry reloaded: %s (active=%s)",
        agent_id,
        row.is_active,
    )
    return AgentResponse.model_validate(row)
