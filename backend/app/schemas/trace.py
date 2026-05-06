"""Trace schemas for Agent Kanban view.

This module defines the Pydantic models for structured trace data,
which is used to render the Kanban view of agent execution.
"""

from pydantic import BaseModel, Field
from uuid import UUID
from datetime import datetime
from typing import Optional, List, Dict, Any, Literal


# ============================================================================
# Base models
# ============================================================================


class ToolCall(BaseModel):
    """A tool call issued by the AI."""

    name: str = Field(..., description="Tool name")
    args: Dict[str, Any] = Field(default_factory=dict, description="Tool arguments")
    id: Optional[str] = Field(None, description="Tool call ID (for matching results)")


class ToolResultInfo(BaseModel):
    """Tool execution result."""

    tool_call_id: Optional[str] = Field(None, description="Corresponding tool_call ID")
    name: str = Field(..., description="Tool name")
    args: Dict[str, Any] = Field(default_factory=dict, description="Call arguments")
    output: str = Field(..., description="Tool output")
    latency_ms: Optional[int] = Field(None, description="Execution latency in ms")
    status: Literal["success", "error"] = Field(
        "success", description="Execution status"
    )


class AIMessageInfo(BaseModel):
    """AI message details."""

    content: Optional[str] = Field(None, description="AI response content")
    thinking: Optional[str] = Field(None, description="Thinking/reasoning process")
    tool_calls: List[ToolCall] = Field(
        default_factory=list, description="Issued tool calls"
    )
    model_name: Optional[str] = Field(None, description="Model used")
    latency_ms: Optional[int] = Field(None, description="Generation latency in ms")


class SubagentRun(BaseModel):
    """Subagent execution (black-box view)."""

    name: str = Field(..., description="Subagent name, e.g. 'navigator'")
    input: str = Field(..., description="Input message")
    output: str = Field(..., description="Output result")
    latency_ms: int = Field(0, description="Total execution latency in ms")
    step_count: int = Field(0, description="Number of internal steps")


# ============================================================================
# Agent Turn - Kanban core unit
# ============================================================================


class AgentTurn(BaseModel):
    """Represents a complete agent execution turn.

    Kanban card structure:
    ┌─────────────────────────────────┐
    │ User: 查询天气                   │  ← humanMsg
    ├─────────────────────────────────┤
    │ LLM (qwen-plus)                 │  ← aiMsg (with tool_calls)
    │ └─ Thinking: 用户需要天气...     │
    ├─────────────────────────────────┤
    │ [Parallel] Tool 1 → Tool 2      │  ← toolMsgs
    ├─────────────────────────────────┤
    │ [Subagent: navigator]           │  ← subagentRuns (black-box)
    ├─────────────────────────────────┤
    │ AI Final Response               │  ← aiFinalResponse
    └─────────────────────────────────┘
    """

    turn_id: str = Field(..., description="Turn ID, e.g. 'turn-1'")
    session_id: Optional[str] = Field(
        None, description="Session UUID for fetching raw steps"
    )
    humanMsg: str = Field(..., description="User input message")
    aiMsg: AIMessageInfo = Field(
        default_factory=lambda: AIMessageInfo(
            content=None, thinking=None, model_name=None, latency_ms=None
        ),
        description="AI response (with tool_calls, final response for simple chats)",
    )
    toolMsgs: List[ToolResultInfo] = Field(
        default_factory=list, description="List of tool execution results"
    )
    subagentRuns: List[SubagentRun] = Field(
        default_factory=list, description="List of subagent executions"
    )
    isParallelTools: bool = Field(
        False, description="Whether tools were called in parallel"
    )
    aiFinalResponse: Optional[AIMessageInfo] = Field(
        None, description="Final AI response after multi-round tool calls"
    )
    total_latency_ms: int = Field(0, description="Total turn latency in ms")
    started_at: datetime = Field(default_factory=datetime.utcnow)


# ============================================================================
# Agent Trace - complete conversation trace
# ============================================================================


class TraceListItem(BaseModel):
    """Trace list item (for trace list view)."""

    thread_id: UUID
    title: str
    total_turns: int
    total_latency_ms: int
    last_updated: datetime = Field(default_factory=datetime.utcnow)


class TraceListResponse(BaseModel):
    """Response wrapper for trace list with pagination metadata."""

    items: List[TraceListItem]
    total: int = 0  # Total items matching the filter
    total_pages: int = 0  # Total number of pages
    page: int = 0  # Current page number
    page_size: int = 0  # Items per page
    has_more: bool = False  # Whether there are more items after this page
    filter_hours: int = 24  # Time filter applied (hours back from now)


class AgentTrace(BaseModel):
    """Agent complete execution trace (data source for Kanban view)."""

    thread_id: UUID = Field(..., description="Conversation thread ID")
    title: str = Field("Untitled Conversation", description="Conversation title")
    turns: List[AgentTurn] = Field(default_factory=list, description="List of turns")
    total_turns: int = Field(0, description="Total number of turns")
    total_tool_calls: int = Field(0, description="Total number of tool calls")
    total_subagent_calls: int = Field(0, description="Total number of subagent calls")
    total_latency_ms: int = Field(0, description="Total execution latency in ms")
    generated_at: datetime = Field(default_factory=datetime.utcnow)

    class Config:
        from_attributes = True
