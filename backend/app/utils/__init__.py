"""Utility functions and helpers for AgentHub.

This package contains pure utilities with no business logic:
- streaming: SSE streaming service for FastAPI
- stream_helpers: Token counting and model resolution
- checkpoint: LangGraph checkpoint history reader
- trace: Execution trace builder
- dag: Execution DAG builder
- parsers: Message parsing utilities
- agent_execution: Token + DAG persistence service
"""

from app.utils.streaming import ChatStreamingService, AsyncWriteQueue
from app.utils.stream_helpers import (
    empty_totals,
    extract_usage,
    accumulate_usage,
    resolve_model_name,
)
from app.utils.checkpoint import CheckpointReader
from app.utils.trace import TraceBuilder
from app.utils.dag import DagBuilder
from app.utils.agent_execution import AgentExecutionService

__all__ = [
    # Streaming
    "ChatStreamingService",
    "AsyncWriteQueue",
    # Token helpers
    "empty_totals",
    "extract_usage",
    "accumulate_usage",
    "resolve_model_name",
    # Checkpoint & Trace
    "CheckpointReader",
    "TraceBuilder",
    "DagBuilder",
    # Persistence
    "AgentExecutionService",
]
