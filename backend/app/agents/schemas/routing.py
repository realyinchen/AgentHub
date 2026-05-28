"""Routing decision schemas for the Supervisor agent."""

from typing import Literal
from pydantic import BaseModel, Field


class RoutingDecision(BaseModel):
    """Structured routing decision produced by the Supervisor agent.

    Forces the supervisor to explicitly declare whether it is routing
    to a subagent or replying directly, along with its reasoning.
    """

    action: Literal["route_to_subagent", "direct_reply"] = Field(
        ...,
        description=(
            "Whether to delegate to a specialist subagent or reply directly. "
            "Use 'route_to_subagent' when the request requires a specialist's "
            "capabilities (search, code execution, data analysis, etc.). "
            "Use 'direct_reply' only for simple greetings, chit-chat, or "
            "questions you can answer confidently without any tools."
        ),
    )

    target_agent: str | None = Field(
        default=None,
        description=(
            "Name of the target subagent when action is 'route_to_subagent'. "
            "Must be one of the agents returned by list_agents(). "
            "Set to None when action is 'direct_reply'."
        ),
    )

    reasoning: str = Field(
        ...,
        description=(
            "Brief explanation of why this routing decision was made. "
            "Include the user's intent and which capabilities are needed."
        ),
    )
