"""
Low-level checkpoint history reader for LangGraph agents.

Provides :class:`CheckpointReader` which wraps ``aget_state_history`` and
returns structured :class:`CheckpointInfo` objects.
"""

import logging
from datetime import datetime
from typing import Optional

from langchain_core.messages import BaseMessage
from langchain_core.runnables import RunnableConfig
from langgraph.graph.state import CompiledStateGraph

from app.schemas.trace import CheckpointInfo

logger = logging.getLogger(__name__)


def _parse_timestamp(created_at: Optional[str]) -> Optional[datetime]:
    """Convert StateSnapshot.created_at (ISO 8601 str) to datetime.

    Per the official LangGraph API, ``created_at`` is an ISO 8601 string
    like ``"2024-08-29T19:19:38.821749+00:00"``.
    """
    if not created_at:
        return None
    try:
        return datetime.fromisoformat(created_at)
    except (ValueError, TypeError):
        logger.debug("Could not parse created_at timestamp: %s", created_at)
        return None


def _extract_node_name(state) -> Optional[str]:
    """Extract the node name that produced this checkpoint.

    Uses ``metadata["writes"]`` (official public API), which is a dict
    mapping node names to their output values.  Returns the first key
    if writes exist; falls back to ``next[0]`` for the initial input
    checkpoint where writes may be ``None``.
    """
    metadata = getattr(state, "metadata", None) or {}
    writes: Optional[dict] = metadata.get("writes") if metadata else None

    if writes:
        # The node that just finished executing
        return next(iter(writes.keys()), None)

    # For the initial "input" checkpoint (step=-1), metadata.writes is
    # often None; fall back to the first scheduled node.
    next_nodes = getattr(state, "next", None)
    if next_nodes:
        cleaned = [n for n in next_nodes if n != "__start__"]
        return cleaned[0] if cleaned else None

    return None


class CheckpointReader:
    """Read raw checkpoint history from a LangGraph checkpointer."""

    def __init__(self, agent: CompiledStateGraph):
        self.agent = agent
        self.checkpointer = agent.checkpointer

    async def get_checkpoint_history(self, thread_id: str) -> list[CheckpointInfo]:
        """Get all checkpoints for a thread in chronological order.

        Args:
            thread_id: The thread ID to query.

        Returns:
            Chronologically ordered list of checkpoint metadata.
        """
        config: RunnableConfig = {"configurable": {"thread_id": thread_id}}
        checkpoints: list[CheckpointInfo] = []
        seen_checkpoint_ids: set[str] = set()

        try:
            async for state in self.agent.aget_state_history(config=config):
                checkpoint_id = state.config.get("configurable", {}).get(
                    "checkpoint_id", ""
                )

                # In rare cases (concurrent writes), the same checkpoint
                # can appear twice; skip duplicates by checkpoint_id.
                if checkpoint_id and checkpoint_id in seen_checkpoint_ids:
                    continue
                if checkpoint_id:
                    seen_checkpoint_ids.add(checkpoint_id)

                channel_values = state.values
                messages: list[BaseMessage] = channel_values.get("messages", [])
                last_message = messages[-1] if messages else None

                # Official API: parent_config is a dict, not accessed via getattr
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
                    last_message_type=type(last_message).__name__
                    if last_message
                    else None,
                    has_next=bool(getattr(state, "next", None)),
                    next_nodes=list(state.next) if getattr(state, "next", None) else [],
                )
                checkpoints.append(checkpoint)

        except Exception as e:
            logger.error(f"Error getting checkpoint history: {e}")

        # Reverse to chronological order (aget_state_history returns
        # newest-first; reverse to oldest-first).
        checkpoints.reverse()
        return checkpoints
