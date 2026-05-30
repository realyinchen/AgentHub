"""Agent-related schemas."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class AgentInfo(BaseModel):
    """Agent information returned by the API."""
    model_config = ConfigDict(from_attributes=True)

    agent_id: str
    description: str
    is_active: bool
    created_at: datetime
    updated_at: datetime


class AgentsResponse(BaseModel):
    """Response for listing agents."""
    agents: list[AgentInfo]
    total: int