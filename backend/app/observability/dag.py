"""
Execution DAG builder for LangGraph agent traces.

Provides :class:`DagBuilder` which converts an execution trace into a
directed acyclic graph suitable for visualization.

Edges are derived from checkpoint parent-child relationships (official
``StateSnapshot.parent_config`` API) rather than being a flat linear
chain, so the DAG reflects the true execution topology — critical for
multi-agent, parallel tool-call, and subgraph scenarios.
"""

from langgraph.graph.state import CompiledStateGraph

from app.schemas.trace import DagNode, ExecutionDag, StepOutput
from app.observability.checkpoint import CheckpointReader
from app.observability.trace import TraceBuilder


class DagBuilder:
    """Build execution DAGs from LangGraph checkpoint history."""

    def __init__(self, agent: CompiledStateGraph):
        self._checkpoint_reader = CheckpointReader(agent)
        self._trace_builder = TraceBuilder(agent)

    async def get_execution_dag(self, thread_id: str) -> ExecutionDag:
        """Build the execution DAG for a thread.

        Uses checkpoint parent-child relationships to construct the real
        graph topology.  Each checkpoint's ``parent_config`` points to the
        checkpoint that immediately precedes it in the execution timeline.

        Args:
            thread_id: The thread ID.

        Returns:
            Execution DAG with nodes and edges.
        """
        # ---- 1) Raw checkpoints (with parent pointers) ----
        raw_checkpoints = await self._checkpoint_reader.get_checkpoint_history(
            thread_id
        )

        # ---- 2) Steps (enriched message-level detail) ----
        steps = await self._trace_builder.get_execution_trace(thread_id)

        # Build checkpoint_id → StepOutput lookup
        cid_to_step: dict[str, StepOutput] = {}
        for step in steps:
            if step.checkpoint_id:
                cid_to_step[step.checkpoint_id] = step

        # ---- 3) Build nodes and edges from checkpoint topology ----
        # checkpoint_id → DAG node_id
        cid_to_node_id: dict[str, str] = {}
        nodes: list[DagNode] = []
        edges: list[tuple[str, str]] = []

        for raw in raw_checkpoints:
            cid = raw.checkpoint_id
            if not cid:
                continue

            step = cid_to_step.get(cid)
            node_id = f"node_{cid[:8]}"

            # Use step data if available; fall back to a minimal stub
            if step is None:
                step = StepOutput(
                    step_number=0,
                    message_type=raw.last_message_type or "unknown",
                    content=None,
                    timestamp=raw.timestamp,
                    message_id=None,
                    checkpoint_id=cid,
                    node_name=raw.node_name,
                    ai_metadata=None,
                    tool_metadata=None,
                )

            title = _build_node_title(step)
            node_name = step.node_name or step.message_type
            message_type = step.message_type
            step_number = step.step_number

            node = DagNode(
                node_id=node_id,
                step_number=step_number,
                node_name=node_name,
                title=title,
                message_type=message_type,
                step=step,
            )
            nodes.append(node)
            cid_to_node_id[cid] = node_id

            # Edge: parent → current
            parent_cid = raw.parent_checkpoint_id
            if parent_cid and parent_cid in cid_to_node_id:
                edges.append((cid_to_node_id[parent_cid], node_id))

        return ExecutionDag(
            thread_id=thread_id,
            nodes=nodes,
            edges=edges,
            total_steps=len(steps),
            steps=steps,
        )


def _build_node_title(step: StepOutput) -> str:
    """Build a human-readable title for a DAG node."""
    if step.message_type == "human":
        return f"Human Input #{step.step_number}"

    if step.message_type == "ai":
        if step.ai_metadata and step.ai_metadata.tool_calls:
            return f"AI Call Tool #{step.step_number}"
        return f"AI Response #{step.step_number}"

    if step.message_type == "tool":
        tool_name = step.tool_metadata.tool_name if step.tool_metadata else "unknown"
        return f"Tool: {tool_name} #{step.step_number}"

    return f"Step #{step.step_number}"
