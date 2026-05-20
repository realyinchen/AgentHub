from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field


# ── Base ──────────────────────────────────────────────────────────────


class AgentBase(BaseModel):
    """Shared fields for agent schemas."""

    description: str = Field(
        min_length=1,
        max_length=1024,
        description="A description of what the agent does",
        examples=["A simple chatbot for general conversations"],
    )
    is_active: bool = Field(
        default=True,
        description="Whether the agent is active and available for use",
        examples=[True],
    )


# ── Create (no agent_id, it comes from URL or service) ────────────────


class AgentCreate(AgentBase):
    """Schema for creating a new agent."""

    pass


# ── Update (all fields optional for partial updates) ──────────────────


class AgentUpdate(BaseModel):
    """Schema for partially updating an agent. All fields are optional."""

    description: Optional[str] = Field(
        None,
        min_length=1,
        max_length=1024,
        description="A description of what the agent does",
    )
    is_active: Optional[bool] = Field(
        None,
        description="Whether the agent is active and available for use",
    )


# ── API Response ──────────────────────────────────────────────────────


class AgentResponse(AgentBase):
    """Schema returned to API clients (includes DB timestamps)."""

    agent_id: str = Field(
        description="The unique identifier of the agent",
        examples=["chatbot", "research-assistant"],
    )
    created_at: datetime = Field(description="Timestamp when the agent was created")
    updated_at: datetime = Field(
        description="Timestamp when the agent was last updated"
    )

    model_config = ConfigDict(from_attributes=True)


# ── List Response ─────────────────────────────────────────────────────


class AgentListResponse(BaseModel):
    """Response wrapper for listing agents."""

    agents: List[AgentResponse] = Field(description="List of agents")
    total: int = Field(description="Total number of agents")
    timestamp: datetime = Field(description="Server timestamp for this response")
