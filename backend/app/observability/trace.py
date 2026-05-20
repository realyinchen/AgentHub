"""
Execution trace builder and query interface for LangGraph agents.

Provides :class:`TraceBuilder` which constructs a chronological sequence of
:class:`StepOutput` objects from checkpoint history, and offers convenience
methods for step-level queries and replay.
"""

import logging
from typing import Optional

from langchain_core.messages import BaseMessage
from langchain_core.runnables import RunnableConfig
from langgraph.graph.state import CompiledStateGraph

from app.schemas.trace import CheckpointInfo, StepOutput
from app.observability.checkpoint import _extract_node_name, _parse_timestamp
from app.observability.parsers import extract_step_from_checkpoint

logger = logging.getLogger(__name__)


class TraceBuilder:
    """Build and query execution traces from LangGraph checkpoint history."""

    def __init__(self, agent: CompiledStateGraph):
        self.agent = agent

    async def get_execution_trace(self, thread_id: str) -> list[StepOutput]:
        """Get the complete execution trace for a thread.

        Args:
            thread_id: The thread ID.

        Returns:
            Chronologically ordered list of step outputs.
        """
        config: RunnableConfig = {"configurable": {"thread_id": thread_id}}

        steps: list[StepOutput] = []
        step_number = 0
        seen_checkpoint_ids: set[str] = set()

        try:
            async for state in self.agent.aget_state_history(config=config):
                checkpoint_id = state.config.get("configurable", {}).get(
                    "checkpoint_id", ""
                )
                messages: list[BaseMessage] = state.values.get("messages", [])

                # Skip checkpoints with no messages (e.g. empty initial state)
                if not messages:
                    continue

                # Deduplicate by checkpoint_id (globally unique) rather than
                # message_id, which is unreliable across ToolMessage variants
                # and fork scenarios.
                if checkpoint_id and checkpoint_id in seen_checkpoint_ids:
                    continue
                if checkpoint_id:
                    seen_checkpoint_ids.add(checkpoint_id)

                last_message = messages[-1]
                step_number += 1

                # Build checkpoint info using shared helpers from checkpoint.py
                parent_config = getattr(state, "parent_config", None) or {}
                parent_checkpoint_id = (
                    parent_config.get("configurable", {}).get("checkpoint_id")
                    if parent_config
                    else None
                )

                checkpoint = CheckpointInfo(
                    checkpoint_id=checkpoint_id,
                    thread_id=thread_id,
                    parent_checkpoint_id=parent_checkpoint_id,
                    node_name=_extract_node_name(state),
                    timestamp=_parse_timestamp(getattr(state, "created_at", None)),
                    message_count=len(messages),
                    last_message_type=type(last_message).__name__,
                    has_next=bool(getattr(state, "next", None)),
                    next_nodes=list(state.next) if state.next else [],
                )

                step = extract_step_from_checkpoint(checkpoint, state, step_number)
                if step:
                    steps.append(step)

        except Exception as e:
            logger.error(f"Error building execution trace: {e}")
            import traceback

            logger.error(traceback.format_exc())

        # Reverse to chronological order and renumber
        steps.reverse()
        for i, step in enumerate(steps):
            step.step_number = i + 1

        return steps

    async def get_step_at_checkpoint(
        self, thread_id: str, checkpoint_id: str
    ) -> Optional[StepOutput]:
        """Get a specific step by its checkpoint ID."""
        steps = await self.get_execution_trace(thread_id)
        for step in steps:
            if step.checkpoint_id == checkpoint_id:
                return step
        return None

    async def get_step_by_number(
        self, thread_id: str, step_number: int
    ) -> Optional[StepOutput]:
        """Get a specific step by its 1-based step number."""
        steps = await self.get_execution_trace(thread_id)
        for step in steps:
            if step.step_number == step_number:
                return step
        return None

    async def replay_steps(
        self,
        thread_id: str,
        from_step: int = 0,
        to_step: Optional[int] = None,
    ) -> list[StepOutput]:
        """Replay steps in a range.

        Args:
            thread_id: The thread ID.
            from_step: Start from this step number (1-based, inclusive).
            to_step: End at this step number (exclusive). ``None`` means all remaining.
        """
        steps = await self.get_execution_trace(thread_id)

        if from_step > 0:
            steps = steps[from_step - 1 :]
        if to_step is not None:
            steps = steps[:to_step]

        return steps
