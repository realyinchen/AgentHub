"""Schemas for Agent Trace observability.

Single-file home for all trace-related Pydantic schemas. Grouped into four
logical sections via comment banners — keep this file modular by section,
not by separate files, since all schemas operate on the same data flow
(checkpoint → step → DAG → list view).

Sections:
    1. Checkpoint info — low-level LangGraph checkpoint metadata
    2. Step output     — per-message step model (replaces the legacy
                         ``MessageStep`` schema) + per-type metadata
    3. Execution DAG   — node + edge representation for visualization
    4. Trace listing   — paginated list view for the Trace Kanban UI
"""

import logging
from datetime import datetime
from pydantic import BaseModel, Field


logger = logging.getLogger(__name__)


# ── 1. Checkpoint info ─────────────────────────────────────────────────


class CheckpointInfo(BaseModel):
    """Information about a LangGraph checkpoint."""

    checkpoint_id: str
    thread_id: str
    parent_checkpoint_id: str | None = None
    node_name: str | None = None
    timestamp: datetime | None = None
    message_count: int = 0
    last_message_type: str | None = None
    has_next: bool = False
    next_nodes: list[str] = Field(default_factory=list)


# ── 2. Step output ─────────────────────────────────────────────────────


class AIStepMetadata(BaseModel):
    """Metadata for AI message steps."""

    thinking: str | None = None
    tool_calls: list[dict] | None = None
    model_name: str | None = None


class ToolStepMetadata(BaseModel):
    """Metadata for Tool message steps."""

    tool_name: str
    tool_args: dict = Field(default_factory=dict)
    tool_call_id: str | None = None


class StepOutput(BaseModel):
    """Unified output schema for any message step.

    Represents a single step in the agent execution, whether it's a human input,
    AI response, or tool execution. Populated directly from LangGraph
    checkpointer data via ``observability.TraceBuilder``.
    """

    step_number: int = Field(description="Step number within the turn")
    message_type: str = Field(description="Type: human, ai, or tool")
    content: str | None = Field(None, description="The message content")
    timestamp: datetime | None = Field(None, description="When this step was created")
    message_id: str | None = Field(None, description="Unique message identifier")
    checkpoint_id: str | None = Field(None, description="LangGraph checkpoint ID")
    node_name: str | None = Field(None, description="Name of the graph node")

    # AI-specific fields (only set for ai type)
    ai_metadata: AIStepMetadata | None = Field(
        None, description="AI-specific metadata (thinking, tool_calls, etc.)"
    )

    # Tool-specific fields (only set for tool type)
    tool_metadata: ToolStepMetadata | None = Field(
        None, description="Tool-specific metadata (name, args, output, etc.)"
    )


# ── 3. Execution DAG ───────────────────────────────────────────────────


class DagNode(BaseModel):
    """A node in the execution DAG."""

    node_id: str = Field(description="Unique node identifier")
    step_number: int = Field(description="Corresponding step number")
    node_name: str = Field(description="Graph node name")
    title: str = Field(description="Human-readable title for display")
    message_type: str = Field(description="Type of message")
    step: StepOutput = Field(description="Full step details")


class ExecutionDag(BaseModel):
    """The complete execution DAG for a thread."""

    thread_id: str = Field(description="Thread/conversation ID")
    nodes: list[DagNode] = Field(description="All nodes in the DAG")
    edges: list[tuple[str, str]] = Field(description="Directed edges between nodes")
    total_steps: int = Field(description="Total number of steps")
    steps: list[StepOutput] = Field(description="All step outputs in order")


class ExecutionTrace(BaseModel):
    """Complete execution trace for a thread."""

    thread_id: str = Field(description="Thread/conversation ID")
    steps: list[StepOutput] = Field(description="All steps in execution order")
    total_steps: int = Field(description="Total number of steps")
    first_step_at: datetime | None = Field(None, description="When execution started")
    last_step_at: datetime | None = Field(None, description="When execution ended")


# ── 4. Trace listing ───────────────────────────────────────────────────


class TraceListItem(BaseModel):
    """Lightweight trace information for listing."""

    thread_id: str = Field(description="Thread/conversation ID")
    title: str = Field(description="Conversation title")
    total_steps: int = Field(description="Total number of execution steps")
    total_latency_ms: int = Field(description="Total execution time in milliseconds")
    last_updated: datetime = Field(description="When the conversation was last updated")
    agent_id: str | None = Field(None, description="Associated agent ID")


class TraceListResponse(BaseModel):
    """Paginated response for trace listing."""

    items: list[TraceListItem] = Field(description="List of traces")
    total: int = Field(description="Total number of matching traces")
    total_pages: int = Field(description="Total number of pages")
    page: int = Field(description="Current page number (0-indexed)")
    page_size: int = Field(description="Number of items per page")
    has_more: bool = Field(description="Whether there are more pages available")
    filter_hours: int = Field(description="Applied time filter in hours")
