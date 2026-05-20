"""
Observability layer for AgentHub.

This package provides execution tracing, checkpoint replay, and DAG
visualization for LangGraph-based agents.

Usage::

    from app.observability import CheckpointTraceReader

    reader = CheckpointTraceReader(agent)
    trace = await reader.get_execution_trace(thread_id)
    dag   = await reader.get_execution_dag(thread_id)

Architecture
------------
- **parsers.py** — Pure functions for message content extraction (stateless, testable)
- **checkpoint.py** — :class:`CheckpointReader` for low-level checkpoint history
- **trace.py** — :class:`TraceBuilder` for execution trace construction & queries
- **dag.py** — :class:`DagBuilder` for execution DAG visualization
- **CheckpointTraceReader** — Facade that composes the above modules
"""

from langgraph.graph.state import CompiledStateGraph

from app.observability.checkpoint import CheckpointReader
from app.observability.trace import TraceBuilder
from app.observability.dag import DagBuilder

from app.schemas.trace import (
    CheckpointInfo,
    ExecutionDag,
    StepOutput,
)

__all__ = [
    "CheckpointTraceReader",
    "CheckpointReader",
    "TraceBuilder",
    "DagBuilder",
]


class CheckpointTraceReader:
    """Facade for reconstructing agent execution traces from LangGraph checkpointer.

    Composes :class:`CheckpointReader`, :class:`TraceBuilder`, and
    :class:`DagBuilder` to provide a unified API while keeping each
    concern independently testable and extensible.

    This class maintains full backward compatibility with the original
    monolithic ``checkpoint_trace.py`` interface.
    """

    def __init__(self, agent: CompiledStateGraph):
        self.agent = agent

        # Composed sub-modules
        self._checkpoint_reader = CheckpointReader(agent)
        self._trace_builder = TraceBuilder(agent)
        self._dag_builder = DagBuilder(agent)

    # ------------------------------------------------------------------
    # Checkpoint APIs
    # ------------------------------------------------------------------

    async def get_checkpoint_history(self, thread_id: str) -> list[CheckpointInfo]:
        """Get all checkpoints for a thread (chronological order)."""
        return await self._checkpoint_reader.get_checkpoint_history(thread_id)

    # ------------------------------------------------------------------
    # Trace APIs
    # ------------------------------------------------------------------

    async def get_execution_trace(self, thread_id: str) -> list[StepOutput]:
        """Get the complete execution trace for a thread."""
        return await self._trace_builder.get_execution_trace(thread_id)

    async def get_step_at_checkpoint(
        self, thread_id: str, checkpoint_id: str
    ) -> StepOutput | None:
        """Get a specific step by its checkpoint ID."""
        return await self._trace_builder.get_step_at_checkpoint(
            thread_id, checkpoint_id
        )

    async def get_step_by_number(
        self, thread_id: str, step_number: int
    ) -> StepOutput | None:
        """Get a specific step by its 1-based step number."""
        return await self._trace_builder.get_step_by_number(thread_id, step_number)

    async def replay_steps(
        self, thread_id: str, from_step: int = 0, to_step: int | None = None
    ) -> list[StepOutput]:
        """Replay steps in a range."""
        return await self._trace_builder.replay_steps(thread_id, from_step, to_step)

    # ------------------------------------------------------------------
    # DAG APIs
    # ------------------------------------------------------------------

    async def get_execution_dag(self, thread_id: str) -> ExecutionDag:
        """Build the execution DAG for a thread."""
        return await self._dag_builder.get_execution_dag(thread_id)
