from pydantic import BaseModel, Field
from typing import Any


class UserInput(BaseModel):
    """Basic user input for the agent."""

    content: str = Field(
        description="User input to the agent.",
        examples=["What is the weather in Hefei?"],
    )
    resume: dict[str, Any] | Any | None = Field(
        description="Value to resume execution with.",
        default=None,
        examples=[{"decisions": [{"type": "approve"}]} ],
    )
    thread_id: str | None = Field(
        description="Thread ID to persist and continue a multi-turn conversation.",
        default=None,
        examples=["f47ac10b-58cc-4342-b6c8-9e5a1d2f3b4c"],
    )
