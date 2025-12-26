from pydantic import BaseModel, Field


class AgentInfo(BaseModel):
    """Info about an available agent."""

    agent_id: str = Field(
        description="Agent ID.",
        examples=["research-assistant"],
    )
    description: str = Field(
        description="Description of the agent.",
        examples=["A research assistant for generating research papers."],
    )


class AgentInfoMetadata(BaseModel):
    """Metadata about the available agents."""

    agents: list[AgentInfo] = Field(
        description="List of available agents.",
    )
    default_agent: str = Field(
        description="Default agent id used when none is specified.",
        examples=["research-assistant"],
    )
