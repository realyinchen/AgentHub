from pydantic import BaseModel, Field
from datetime import datetime, timezone


class Agent(BaseModel):
    agent_id: str = Field(
        description="The thread ID of the conversation.",
        examples=["chatbot"],
    )
    description: str = Field(
        description="The thread ID of the conversation.",
        examples=["A simple chatbot"],
        min_length=0,
        max_length=1024,
    )
    is_active: bool | None = Field(
        description="The thread ID of the conversation.",
        default=False,
        examples=[True],
    )


class AgentCreate(Agent):
    pass


class AgentUpdate(Agent):
    pass


class AgentInDB(Agent):
    created_at: datetime = Field(
        description="The create time of the agent", default=datetime.now(timezone.utc)
    )
    updated_at: datetime = Field(
        description="The update time of the agent", default=datetime.now(timezone.utc)
    )

    class Config:
        from_attributes = True
