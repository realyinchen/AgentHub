"""
Execution DAG builder for LangGraph agent traces.

Provides :class:`DagBuilder` which converts a conversation's checkpoint history
into a directed acyclic graph suitable for visualization.

Key improvements over previous version:
1. Uses aget_state_history() for complete execution path
2. Filters checkpoints by before_checkpoint_id to get per-turn DAG
3. Extracts node→message mapping from metadata.writes
4. Builds edges based on actual execution order

Each message (Human, AI, Tool) becomes a node, with edges connecting
messages in execution order to show the conversation flow.
"""

import logging
from typing import Any

from langchain_core.messages import HumanMessage, AIMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from langgraph.graph.state import CompiledStateGraph

from app.schemas.trace import AIStepMetadata, DagNode, ExecutionDag, StepOutput, ToolStepMetadata


logger = logging.getLogger(__name__)


class DagBuilder:
    """Build execution DAGs from LangGraph checkpoint history.

    Uses checkpoint history to reconstruct the complete execution path for a
    single user-agent turn. Each checkpoint's metadata.writes contains the
    node name and its output messages, enabling accurate DAG construction.
    """

    def __init__(self, agent: CompiledStateGraph):
        self.agent = agent

    async def get_execution_dag(
        self,
        thread_id: str,
        before_checkpoint_id: str | None = None,
        before_message_count: int = 0,
    ) -> ExecutionDag:
        """Build the execution DAG for a single user-agent turn.

        Constructs a message-flow DAG where each node represents a message
        (Human, AI, or Tool) in the conversation. Edges connect messages in
        execution order.

        The DAG structure:
        - Entry node: HumanMessage (user input for this turn)
        - Middle nodes: AIMessage, ToolMessage (agent execution)
        - End node: AIMessage (final response)

        Args:
            thread_id: The thread ID.
            before_checkpoint_id: Checkpoint ID before this turn started.
                Used to filter checkpoint history and only extract new checkpoints.
            before_message_count: Number of messages before this turn started.
                Used as fallback if checkpoint history fails.

        Returns:
            Execution DAG with nodes and edges representing the message flow.
        """
        config: RunnableConfig = {"configurable": {"thread_id": thread_id}}

        nodes: list[DagNode] = []
        edges: list[tuple[str, str]] = []
        seen_message_ids: set[str] = set()

        # Get final state to find all messages in this turn
        state = await self.agent.aget_state(config)
        all_messages: list = state.values.get("messages", [])
        new_messages = all_messages[before_message_count:]

        # Find the first HumanMessage in this turn (entry node)
        human_message = None
        for msg in new_messages:
            if isinstance(msg, HumanMessage):
                human_message = msg
                break

        # Build entry node from HumanMessage if exists
        if human_message:
            msg_id = getattr(human_message, "id", None) or str(id(human_message))
            seen_message_ids.add(msg_id)
            step_number = 1
            node = self._build_node_from_message(
                msg=human_message,
                step_number=step_number,
                node_name="__start__",  # Entry point
                checkpoint_id=None,
                timestamp=None,
            )
            nodes.append(node)

        # Primary approach: Extract agent outputs from checkpoint history
        # Also collect next_nodes for edge construction and checkpoint_ns for subgraph
        try:
            # (cp_id, cp_ns, node_name, writes, timestamp, next_nodes)
            checkpoints_data: list[tuple[str | None, str, str, dict, str | None, tuple[str, ...]]] = []

            checkpoint_count = 0
            async for checkpoint in self.agent.aget_state_history(config):
                checkpoint_count += 1

                # Debug: log checkpoint structure
                configurable = checkpoint.config.get("configurable")
                cp_id = configurable.get("checkpoint_id") if configurable else None
                source = checkpoint.metadata.get("source", "") if checkpoint.metadata else ""
                writes = checkpoint.metadata.get("writes", {}) if checkpoint.metadata else {}
                step = checkpoint.metadata.get("step", -1) if checkpoint.metadata else -1

                logger.debug(
                    "Checkpoint #%d: id=%s, source=%s, step=%s, writes_keys=%s, next=%s",
                    checkpoint_count,
                    cp_id,
                    source,
                    step,
                    list(writes.keys()) if writes else [],
                    checkpoint.next,
                )

                # Stop condition: reached the checkpoint before this turn
                if cp_id and cp_id == before_checkpoint_id:
                    logger.debug("Stopping at before_checkpoint_id=%s", before_checkpoint_id)
                    break

                # Get checkpoint namespace to identify subgraphs
                # "" = root graph, "node_name:uuid" = subgraph
                cp_ns = configurable.get("checkpoint_ns", "") if configurable else ""

                # Get next nodes to execute (for edge construction)
                next_nodes = checkpoint.next if checkpoint.next else ()
                timestamp = checkpoint.created_at

                # Skip input checkpoint (step=-1, source=input) - already handled above
                if source == "input":
                    logger.debug("Skipping input checkpoint")
                    continue

                for node_name, output in writes.items():
                    if not isinstance(output, dict):
                        logger.debug("Skipping non-dict output: %s", type(output))
                        continue
                    logger.debug(
                        "Adding checkpoint data: cp_id=%s, cp_ns=%s, node_name=%s, output_keys=%s",
                        cp_id,
                        cp_ns,
                        node_name,
                        list(output.keys()),
                    )
                    checkpoints_data.append((cp_id or "", cp_ns, node_name, output, timestamp, next_nodes))

            logger.info(
                "Checkpoint history: %d total checkpoints, %d valid for thread=%s",
                checkpoint_count,
                len(checkpoints_data),
                thread_id,
            )

            # If no checkpoints found, fall back to message slice
            if not checkpoints_data:
                logger.info(
                    "No checkpoints found in history, falling back to message slice for thread=%s",
                    thread_id,
                )
                # Get all messages from final state for this turn
                checkpoint_nodes = await self._build_from_message_slice(thread_id, before_message_count)
                # Skip the first node if it's the human message (already added above)
                for node in checkpoint_nodes:
                    if node.message_type == "human" and human_message:
                        continue  # Skip duplicate human node
                    nodes.append(node)
            else:
                # Reverse to chronological order (oldest first)
                checkpoints_data.reverse()

                # Track which node_id corresponds to which step_number
                node_id_to_step: dict[str, int] = {}

                # Build nodes from checkpoints (agent outputs)
                # Include checkpoint_ns info for subgraph identification
                for cp_id, cp_ns, node_name, output, timestamp, next_nodes in checkpoints_data:
                    messages = output.get("messages", [])
                    for msg in messages:
                        msg_id = getattr(msg, "id", None) or str(id(msg))
                        if msg_id in seen_message_ids:
                            continue
                        seen_message_ids.add(msg_id)

                        step_number = len(nodes) + 1
                        # Prefix node_name with cp_ns for subgraph nodes
                        display_node_name = f"{cp_ns}:{node_name}" if cp_ns else node_name
                        node = self._build_node_from_message(
                            msg=msg,
                            step_number=step_number,
                            node_name=display_node_name,
                            checkpoint_id=cp_id,
                            timestamp=timestamp,
                        )
                        nodes.append(node)
                        node_id_to_step[node.node_id] = step_number

            logger.info(
                "Built DAG from checkpoint history: %d nodes (entry=%s), %d checkpoints for thread=%s",
                len(nodes),
                "human" if human_message else "none",
                len(checkpoints_data),
                thread_id,
            )

        except Exception as e:
            logger.warning(
                "Failed to get checkpoint history for thread=%s: %s, falling back to message slice",
                thread_id,
                e,
            )
            # Fallback: Use message slice from final state
            nodes = await self._build_from_message_slice(thread_id, before_message_count)

        # Build edges: connect nodes in execution order
        # Use simple linear connection for now (more sophisticated edge construction
        # would require additional checkpoint metadata about node transitions)
        for i in range(len(nodes) - 1):
            edges.append((nodes[i].node_id, nodes[i + 1].node_id))

        # Ensure DAG has at least the entry→first_output edge
        if len(nodes) >= 2:
            first_edge = (nodes[0].node_id, nodes[1].node_id)
            if first_edge not in edges:
                edges.insert(0, first_edge)

        return ExecutionDag(
            thread_id=thread_id,
            nodes=nodes,
            edges=edges,
            total_steps=len(nodes),
            steps=[n.step for n in nodes],
        )

    async def _build_from_message_slice(
        self,
        thread_id: str,
        before_message_count: int,
    ) -> list[DagNode]:
        """Fallback: Build nodes from message slice when checkpoint history fails.

        Args:
            thread_id: The thread ID.
            before_message_count: Number of messages before this turn.

        Returns:
            List of DagNode objects.
        """
        config: RunnableConfig = {"configurable": {"thread_id": thread_id}}
        state = await self.agent.aget_state(config)
        messages: list = state.values.get("messages", [])

        # Only extract messages from this turn
        new_messages = messages[before_message_count:]

        nodes: list[DagNode] = []
        for i, msg in enumerate(new_messages):
            step_number = i + 1
            node = self._build_node_from_message(
                msg=msg,
                step_number=step_number,
                node_name=None,
                checkpoint_id=None,
                timestamp=None,
            )
            nodes.append(node)

        logger.info(
            "Built DAG from message slice: %d nodes (skipped %d existing) for thread=%s",
            len(nodes),
            before_message_count,
            thread_id,
        )

        return nodes

    def _build_node_from_message(
        self,
        msg: Any,
        step_number: int,
        node_name: str | None,
        checkpoint_id: str | None,
        timestamp: Any | None,
    ) -> DagNode:
        """Build a DagNode from a message object.

        Args:
            msg: The message (HumanMessage, AIMessage, ToolMessage, etc.)
            step_number: Step number within this turn.
            node_name: Graph node name that produced this message.
            checkpoint_id: Checkpoint ID where this message was recorded.
            timestamp: When this checkpoint was created.

        Returns:
            DagNode object.
        """
        # Determine message_type
        if isinstance(msg, HumanMessage):
            message_type = "human"
            content = _convert_content_to_string(msg.content)
        elif isinstance(msg, AIMessage):
            message_type = "ai"
            content = _convert_content_to_string(msg.content)
        elif isinstance(msg, ToolMessage):
            message_type = "tool"
            content = _convert_content_to_string(msg.content)
        else:
            message_type = "unknown"
            content = str(msg.content) if hasattr(msg, "content") else ""

        # Build StepOutput
        step = StepOutput(
            step_number=step_number,
            message_type=message_type,
            content=content,
            timestamp=timestamp,
            message_id=getattr(msg, "id", None),
            checkpoint_id=checkpoint_id,
            node_name=node_name,
            ai_metadata=None,
            tool_metadata=None,
        )

        # Add AI-specific metadata
        if isinstance(msg, AIMessage):
            thinking = _extract_thinking(msg)
            tool_calls = getattr(msg, "tool_calls", None)
            step.ai_metadata = AIStepMetadata(
                thinking=thinking if thinking else None,
                tool_calls=tool_calls if tool_calls else None,
                model_name=None,
            )

        # Add Tool-specific metadata
        if isinstance(msg, ToolMessage):
            step.tool_metadata = ToolStepMetadata(
                tool_name=getattr(msg, "name", "") or "",
                tool_args={},
                tool_call_id=getattr(msg, "tool_call_id", None),
            )

        # Build node
        node_id = f"node_{step_number}"
        title = _build_node_title(step)

        # Use actual node_name if available, otherwise use message_type
        display_node_name = node_name if node_name else message_type

        return DagNode(
            node_id=node_id,
            step_number=step_number,
            node_name=display_node_name,
            title=title,
            message_type=message_type,
            step=step,
        )


def _convert_content_to_string(content) -> str:
    """Convert message content to string."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        text_parts = []
        for item in content:
            if isinstance(item, str):
                text_parts.append(item)
            elif isinstance(item, dict) and item.get("type") == "text":
                text_parts.append(item.get("text", ""))
        return "".join(text_parts)
    return str(content) if content else ""


def _extract_thinking(message) -> str:
    """Extract thinking content from an AI message."""
    thinking = ""

    # Structured content
    if isinstance(message.content, list):
        thinking_blocks = []
        for block in message.content:
            if isinstance(block, dict) and block.get("type") == "thinking":
                thinking_blocks.append(block.get("thinking", ""))
        thinking = "".join(thinking_blocks)

    # reasoning_content attribute (DeepSeek-R1 style)
    if not thinking:
        reasoning_attr = getattr(message, "reasoning_content", None)
        if reasoning_attr:
            if isinstance(reasoning_attr, str):
                thinking = reasoning_attr
            elif isinstance(reasoning_attr, list):
                thinking = "".join(str(p) for p in reasoning_attr if isinstance(p, str))

    return thinking.strip()


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