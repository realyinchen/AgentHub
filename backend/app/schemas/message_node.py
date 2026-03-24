from pydantic import BaseModel, Field
from typing import Any, Literal
from uuid import UUID
from datetime import datetime, timezone


class MessageNodeBase(BaseModel):
    """Base schema for message node."""

    role: Literal["user", "assistant"] = Field(
        description="Role of the message sender.",
        examples=["user", "assistant"],
    )
    content: str = Field(
        description="Content of the message.",
        examples=["Hello, how are you?"],
    )
    parent_id: UUID | None = Field(
        description="Parent node ID for tree structure.",
        default=None,
        examples=["f47ac10b-58cc-4342-b6c8-9e5a1d2f3b4c"],
    )
    branch_index: int = Field(
        description="Branch index for ordering siblings.",
        default=0,
        examples=[0, 1, 2],
    )
    tool_calls: list[dict[str, Any]] | None = Field(
        description="Tool calls in the message.",
        default=None,
    )
    tool_call_status: Literal["pending", "completed", "failed"] | None = Field(
        description="Status of tool calls.",
        default=None,
        examples=["pending", "completed", "failed"],
    )
    custom_data: dict[str, Any] | None = Field(
        description="Custom message data.",
        default=None,
    )


class MessageNodeCreate(MessageNodeBase):
    """Schema for creating a message node."""

    thread_id: UUID = Field(
        description="Thread ID this message belongs to.",
        examples=["f47ac10b-58cc-4342-b6c8-9e5a1d2f3b4c"],
    )


class MessageNodeUpdate(BaseModel):
    """Schema for updating a message node."""

    content: str | None = Field(
        description="Updated content of the message.",
        default=None,
    )
    tool_calls: list[dict[str, Any]] | None = Field(
        description="Updated tool calls.",
        default=None,
    )
    tool_call_status: Literal["pending", "completed", "failed"] | None = Field(
        description="Updated status of tool calls.",
        default=None,
    )
    custom_data: dict[str, Any] | None = Field(
        description="Updated custom message data.",
        default=None,
    )


class MessageNodeInDB(MessageNodeBase):
    """Schema for message node in database."""

    id: UUID = Field(
        description="Unique ID of the message node.",
        examples=["f47ac10b-58cc-4342-b6c8-9e5a1d2f3b4c"],
    )
    thread_id: UUID = Field(
        description="Thread ID this message belongs to.",
        examples=["f47ac10b-58cc-4342-b6c8-9e5a1d2f3b4c"],
    )
    created_at: datetime = Field(
        description="Creation timestamp.",
        default_factory=lambda: datetime.now(timezone.utc),
    )
    children_ids: list[UUID] = Field(
        description="IDs of child nodes.",
        default=[],
    )

    class Config:
        from_attributes = True


class MessageTree(BaseModel):
    """Schema for the complete message tree."""

    nodes: list[MessageNodeInDB] = Field(
        description="All message nodes in the conversation.",
        default=[],
    )
    root_id: UUID | None = Field(
        description="ID of the root node.",
        default=None,
    )
    current_leaf_id: UUID | None = Field(
        description="ID of the current leaf node.",
        default=None,
    )


class CurrentLeafUpdate(BaseModel):
    """Schema for updating current leaf node."""

    current_leaf_id: UUID = Field(
        description="ID of the new current leaf node.",
        examples=["f47ac10b-58cc-4342-b6c8-9e5a1d2f3b4c"],
    )