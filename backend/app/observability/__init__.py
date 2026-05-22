"""
Observability layer for AgentHub.

This package provides execution tracing, checkpoint replay, and DAG
visualization for LangGraph-based agents.

Usage::

    from app.observability import CheckpointReader, TraceBuilder, DagBuilder

    reader = CheckpointReader(agent)
    history = await reader.get_checkpoint_history(thread_id)

    builder = TraceBuilder(agent)
    trace = await builder.get_execution_trace(thread_id)

    dag_builder = DagBuilder(agent)
    dag = await dag_builder.get_execution_dag(thread_id)

Architecture
------------
- **parsers.py** — Pure functions for message content extraction (stateless, testable)
- **checkpoint.py** — :class:`CheckpointReader` for low-level checkpoint history
- **trace.py** — :class:`TraceBuilder` for execution trace construction & queries
- **dag.py** — :class:`DagBuilder` for execution DAG visualization
"""

from app.observability.checkpoint import CheckpointReader
from app.observability.trace import TraceBuilder
from app.observability.dag import DagBuilder

__all__ = [
    "CheckpointReader",
    "TraceBuilder",
    "DagBuilder",
]
