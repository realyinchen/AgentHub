"""Utility functions and helpers for AgentHub.

This package contains pure utilities with no business logic:
- request: Agent parameter building (build_agent_kwargs)
- sse: SSE streaming utilities for FastAPI
- message: Message parsing and token utilities
- checkpoint: LangGraph checkpoint history reader
- trace: Execution trace builder
- dag: Execution DAG builder

Note: ChatStreamingService moved to app.services.streaming.py (P1).
"""

from app.utils.request import build_agent_kwargs, AgentKwargs
from app.utils.sse import AsyncWriteQueue
from app.utils.message import (
    empty_totals,
    extract_usage,
    accumulate_usage,
    langchain_to_chat_message,
)
from app.utils.checkpoint import CheckpointReader
from app.utils.trace import TraceBuilder
from app.utils.dag import DagBuilder

__all__ = [
    # Request building
    "build_agent_kwargs",
    "AgentKwargs",
    # Streaming utilities
    "AsyncWriteQueue",
    # Message & Token helpers
    "empty_totals",
    "extract_usage",
    "accumulate_usage",
    "langchain_to_chat_message",
    # Checkpoint & Trace
    "CheckpointReader",
    "TraceBuilder",
    "DagBuilder",
]
