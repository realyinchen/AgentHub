from pydantic import BaseModel, Field
from datetime import datetime, timezone
from typing import Optional


class Agent(BaseModel):
    agent_id: str = Field(
        description="The unique identifier of the agent",
        examples=["chatbot", "research-assistant"],
    )
    description: str = Field(
        description="A description of what the agent does",
        examples=["A simple chatbot for general conversations"],
        min_length=0,
        max_length=1024,
    )
    is_active: Optional[bool] = Field(
        description="Whether the agent is active and available for use",
        default=True,
        examples=[True],
    )


class AgentCreate(Agent):
    pass


class AgentUpdate(BaseModel):
    agent_id: Optional[str] = Field(
        None,
        description="The unique identifier of the agent",
        examples=["chatbot"],
    )
    description: Optional[str] = Field(
        None,
        description="A description of what the agent does",
        examples=["A simple chatbot for general conversations"],
        min_length=0,
        max_length=1024,
    )
    is_active: Optional[bool] = Field(
        None,
        description="Whether the agent is active and available for use",
        examples=[True],
    )


class AgentInDB(Agent):
    created_at: datetime = Field(
        description="Timestamp when the agent was created",
        default_factory=lambda: datetime.now(timezone.utc),
    )
    updated_at: datetime = Field(
        description="Timestamp when the agent was last updated",
        default_factory=lambda: datetime.now(timezone.utc),
    )

    class Config:
        from_attributes = True
