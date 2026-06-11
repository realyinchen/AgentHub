"""
Execution DAG builder for LangGraph agent traces.

Provides :class:`DagBuilder` which converts a conversation's checkpoint history
into a directed acyclic graph suitable for visualization.

Key approach:
1. Get all messages from final state for this turn
2. Infer execution flow from message types and relationships:
   - HumanMessage → User node
   - AIMessage + tool_calls → AI decision node (with tool calls)
   - ToolMessage → Tool execution node (linked via tool_call_id)
3. Build edges based on actual execution order

This approach is more reliable than checkpoint metadata parsing because:
- It works regardless of checkpoint storage format
- It correctly handles parallel tool calls
- It captures the logical execution flow
"""

import logging

from langchain_core.messages import HumanMessage, AIMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from langgraph.graph.state import CompiledStateGraph

from app.schemas.trace import (
    AIStepMetadata,
    DagNode,
    ExecutionDag,
    StepOutput,
    ToolStepMetadata,
)


logger = logging.getLogger(__name__)


class DagBuilder:
    """Build execution DAGs from LangGraph checkpoint history.

    Uses message-based inference to reconstruct the execution path for a
    single user-agent turn. The DAG structure reflects the logical flow:
    Human → AI (with tool calls) → Tools → AI (with tool calls) → ... → AI (final)
    """

    def __init__(self, agent: CompiledStateGraph):
        self.agent = agent

    async def get_execution_dag(
        self,
        thread_id: str,
        before_checkpoint_id: str | None = None,
        before_message_count: int = 0,
        reasoning_segments: dict[str, str] | None = None,
    ) -> ExecutionDag:
        """Build the execution DAG for a single user-agent turn.

        Uses message-based inference to construct the DAG:
        1. HumanMessage → User node (entry)
        2. AIMessage with tool_calls → AI node + creates pending tool nodes
        3. ToolMessage → Tool node (matched to AI node via tool_call_id)
        4. AIMessage without tool_calls → Final AI response

        Args:
            thread_id: The thread ID.
            before_checkpoint_id: Checkpoint ID before this turn started.
                Used to determine if this is a continuation.
            before_message_count: Number of messages before this turn started.
            reasoning_segments: Dict mapping AIMessage.id to reasoning content.
                Used to inject thinking into each AI node in the DAG when
                checkpointer doesn't preserve reasoning content.

        Returns:
            Execution DAG with nodes and edges representing the message flow.
        """
        config: RunnableConfig = {"configurable": {"thread_id": thread_id}}

        # Get final state to find all messages in this turn
        state = await self.agent.aget_state(config)
        all_messages: list = state.values.get("messages", [])
        new_messages = all_messages[before_message_count:]

        if not new_messages:
            logger.warning("No messages found for thread=%s", thread_id)
            return ExecutionDag(
                thread_id=thread_id,
                nodes=[],
                edges=[],
                total_steps=0,
                steps=[],
            )

        # Build nodes using message-based inference
        nodes, edges = self._build_dag_from_messages(new_messages, reasoning_segments)

        return ExecutionDag(
            thread_id=thread_id,
            nodes=nodes,
            edges=edges,
            total_steps=len(nodes),
            steps=[n.step for n in nodes],
        )

    def _build_dag_from_messages(
        self,
        messages: list,
        reasoning_segments: dict[str, str] | None = None,
    ) -> tuple[list[DagNode], list[tuple[str, str]]]:
        """Build DAG nodes and edges from a list of messages.

        This is the core logic that infers execution flow from message types
        and relationships.

        Args:
            messages: List of messages for this turn.
            reasoning_segments: Dict mapping AIMessage.id to reasoning content.
                Used to inject thinking into each AI node in the DAG when
                checkpointer doesn't preserve reasoning content.

        Returns:
            Tuple of (nodes list, edges list).
        """
        nodes: list[DagNode] = []
        edges: list[tuple[str, str]] = []

        # Track tool calls to match ToolMessages to their source AI nodes
        # Key: unique identifier (tool_call_id or generated key)
        # Value: (ai_node_id, tool_name, tool_args, order_index)
        pending_tool_calls: dict[str, tuple[str, str, dict, int]] = {}
        tool_call_counter = 0  # Global counter for generating unique IDs

        # Track the last node for each "layer" to build edges correctly
        last_user_node: str | None = None
        last_ai_node: str | None = None
        last_tool_nodes: list[str] = []  # For parallel tools

        # Track AI node indices and their message IDs for reasoning injection
        ai_node_indices: list[tuple[int, str]] = []  # (node_index, message_id)

        step_number = 0

        for msg_idx, msg in enumerate(messages):
            if isinstance(msg, HumanMessage):
                # User input node
                step_number += 1
                node = self._build_human_node(msg, step_number)
                nodes.append(node)
                last_user_node = node.node_id

            elif isinstance(msg, AIMessage):
                step_number += 1
                msg_id = getattr(msg, "id", None) or str(id(msg))
                node = self._build_ai_node(msg, step_number)
                nodes.append(node)

                # Track AI node index and message_id for reasoning injection
                ai_node_indices.append((len(nodes) - 1, msg_id))

                # Build edge from previous node
                if last_user_node and not last_ai_node:
                    # First AI after user
                    edges.append((last_user_node, node.node_id))
                elif last_tool_nodes:
                    # AI after tools (tools → AI)
                    for tool_node_id in last_tool_nodes:
                        edges.append((tool_node_id, node.node_id))
                elif last_ai_node:
                    # AI after AI (shouldn't normally happen, but handle it)
                    edges.append((last_ai_node, node.node_id))

                last_ai_node = node.node_id
                last_tool_nodes = []

                # Register tool calls from this AI message
                if msg.tool_calls:
                    for tc in msg.tool_calls:
                        # Use tool_call_id if available, otherwise generate unique key
                        tc_id = tc.get("id")
                        tool_name = tc.get("name", "unknown")
                        tool_args = tc.get("args", {})

                        # If tool_call_id is missing or empty, generate a unique key
                        if not tc_id:
                            tc_id = f"__gen_{tool_name}_{tool_call_counter}"
                            logger.debug(
                                "Tool call without id, generated: %s for tool=%s",
                                tc_id,
                                tool_name,
                            )

                        tool_call_counter += 1
                        pending_tool_calls[tc_id] = (
                            node.node_id,
                            tool_name,
                            tool_args,
                            tool_call_counter,
                        )

            elif isinstance(msg, ToolMessage):
                # Find matching tool call
                tool_call_id = getattr(msg, "tool_call_id", None)
                tool_name_from_msg = getattr(msg, "name", None)

                if not tool_call_id:
                    # Fallback: try to match by tool name
                    if tool_name_from_msg:
                        for tc_id, (ai_node_id, name, args, order) in list(
                            pending_tool_calls.items()
                        ):
                            if name == tool_name_from_msg:
                                tool_call_id = tc_id
                                break

                    if not tool_call_id:
                        logger.debug(
                            "ToolMessage without tool_call_id and no name match, skipping. name=%s",
                            tool_name_from_msg,
                        )
                        continue

                pending = pending_tool_calls.pop(tool_call_id, None)
                if not pending:
                    logger.debug(
                        "ToolMessage with unmatched tool_call_id=%s, skipping",
                        tool_call_id,
                    )
                    continue

                source_ai_node_id, tool_name, tool_args, _order = pending

                step_number += 1
                node = self._build_tool_node(
                    msg=msg,
                    step_number=step_number,
                    tool_name=tool_name,
                    tool_args=tool_args,
                )
                nodes.append(node)
                last_tool_nodes.append(node.node_id)

                # Edge: AI → Tool
                edges.append((source_ai_node_id, node.node_id))

            else:
                logger.warning("Unknown message type: %s", type(msg).__name__)

        # ── Inject reasoning segments into each AI node ──────────────────────────
        # For each AI node, check if there's a matching reasoning segment from streaming.
        # If the segment is longer than existing thinking (from checkpointer), inject it.
        if reasoning_segments:
            thinking_status = reasoning_segments.get("__thinking_status__")
            raw_segments = [
                segment
                for key, segment in reasoning_segments.items()
                if not key.startswith("__") and segment
            ]
            for ai_order, (node_idx, msg_id) in enumerate(ai_node_indices):
                if 0 <= node_idx < len(nodes):
                    ai_node = nodes[node_idx]
                    if ai_node.message_type == "ai":
                        # Prefer exact message id, then fall back to AI order. LangGraph
                        # can serialize checkpoint messages with ids that differ from the
                        # streaming projection object, especially for non-streaming provider
                        # adapters.
                        segment = reasoning_segments.get(msg_id, "")
                        if not segment:
                            segment = reasoning_segments.get(
                                f"__ai_index_{ai_order}",
                                "",
                            )
                        if not segment and len(ai_node_indices) == 1:
                            segment = reasoning_segments.get("__latest__", "")
                        if (
                            not segment
                            and len(ai_node_indices) == 1
                            and len(raw_segments) == 1
                        ):
                            segment = raw_segments[0]
                        if segment:
                            existing_thinking = ai_node.step.thinking or ""
                            # Replace if segment is longer (more complete)
                            if len(segment) > len(existing_thinking):
                                # Update the step's thinking field
                                ai_node.step.thinking = segment
                                # Also update ai_metadata if it exists
                                if ai_node.step.ai_metadata:
                                    ai_node.step.ai_metadata.thinking = segment
                        elif thinking_status:
                            ai_node.step.thinking_status = thinking_status
                            if ai_node.step.ai_metadata:
                                ai_node.step.ai_metadata.thinking_status = (
                                    thinking_status
                                )

        return nodes, edges

    def _build_human_node(self, msg: HumanMessage, step_number: int) -> DagNode:
        """Build a user input node from a HumanMessage."""
        content = _convert_content_to_string(msg.content)
        msg_id = getattr(msg, "id", None) or str(id(msg))

        step = StepOutput(
            step_number=step_number,
            message_type="human",
            content=content,
            timestamp=None,
            message_id=msg_id,
            checkpoint_id=None,
            node_name="__start__",
            ai_metadata=None,
            tool_metadata=None,
            # Flattened fields (all None for human messages)
            thinking=None,
            thinking_status=None,
            tool_calls=None,
            model_name=None,
            tool_name=None,
            tool_args=None,
            tool_output=None,
            tool_call_id=None,
        )

        return DagNode(
            node_id=f"human_{step_number}",
            step_number=step_number,
            node_name="user",
            title="User Input",
            message_type="human",
            step=step,
        )

    def _build_ai_node(self, msg: AIMessage, step_number: int) -> DagNode:
        """Build an AI node from an AIMessage."""
        content = _convert_content_to_string(msg.content)
        thinking = _extract_thinking(msg)
        tool_calls = getattr(msg, "tool_calls", None)
        msg_id = getattr(msg, "id", None) or str(id(msg))

        # Determine if this is a final response or intermediate
        is_final = not tool_calls or len(tool_calls) == 0

        step = StepOutput(
            step_number=step_number,
            message_type="ai",
            content=content,
            timestamp=None,
            message_id=msg_id,
            checkpoint_id=None,
            node_name="model",
            ai_metadata=AIStepMetadata(
                thinking=thinking if thinking else None,
                thinking_status=None,
                tool_calls=tool_calls if tool_calls else None,
                model_name=getattr(msg, "model_name", None),
            ),
            tool_metadata=None,
            # Flattened fields for AI messages
            thinking=thinking if thinking else None,
            thinking_status=None,
            tool_calls=tool_calls if tool_calls else None,
            model_name=getattr(msg, "model_name", None),
            tool_name=None,
            tool_args=None,
            tool_output=None,
            tool_call_id=None,
        )

        # Build title
        if is_final:
            title = "AI Response"
        else:
            tool_names = [tc.get("name", "unknown") for tc in (tool_calls or [])]
            title = f"AI → {', '.join(tool_names)}"

        return DagNode(
            node_id=f"ai_{step_number}",
            step_number=step_number,
            node_name="model",
            title=title,
            message_type="ai",
            step=step,
        )

    def _build_tool_node(
        self,
        msg: ToolMessage,
        step_number: int,
        tool_name: str,
        tool_args: dict,
    ) -> DagNode:
        """Build a tool execution node from a ToolMessage."""
        content = _convert_content_to_string(msg.content)
        msg_id = getattr(msg, "id", None) or str(id(msg))
        tool_call_id = getattr(msg, "tool_call_id", None)

        step = StepOutput(
            step_number=step_number,
            message_type="tool",
            content=content,
            timestamp=None,
            message_id=msg_id,
            checkpoint_id=None,
            node_name=tool_name,
            ai_metadata=None,
            tool_metadata=ToolStepMetadata(
                tool_name=tool_name,
                tool_args=tool_args,
                tool_call_id=tool_call_id,
            ),
            # Flattened fields for tool messages
            thinking=None,
            thinking_status=None,
            tool_calls=None,
            model_name=None,
            tool_name=tool_name,
            tool_args=tool_args,
            tool_output=content,  # Tool output is the message content
            tool_call_id=tool_call_id,
        )

        return DagNode(
            node_id=f"tool_{step_number}",
            step_number=step_number,
            node_name=tool_name,
            title=f"🔧 {tool_name}",
            message_type="tool",
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
            elif isinstance(item, dict):
                if item.get("type") == "text":
                    text_parts.append(item.get("text", ""))
                elif item.get("type") == "thinking":
                    # Skip thinking blocks in content, they're extracted separately
                    pass
        return "".join(text_parts)
    return str(content) if content else ""


def _extract_thinking(message) -> str:
    """Extract thinking content from an AI message.

    Supports multiple formats:
    1. Structured content with type='thinking' blocks
    2. reasoning_content attribute (DeepSeek-R1 style)
    3. non_standard content blocks (Qwen thinking mode)
    4. additional_kwargs['thinking'] (persisted from streaming)
    5. additional_kwargs['reasoning_content'] (some providers)
    """
    thinking = ""

    # 1. Structured content with type='thinking' blocks
    if isinstance(message.content, list):
        thinking_blocks = []
        for block in message.content:
            if isinstance(block, dict):
                block_type = block.get("type")

                if block_type == "thinking":
                    thinking_blocks.append(block.get("thinking", ""))

                elif block_type == "non_standard":
                    # Qwen style: {"type": "non_standard", "value": {"type": "thinking", "thinking": "..."}}
                    # The value might contain thinking content
                    value = block.get("value", {})
                    if isinstance(value, dict):
                        if value.get("type") == "thinking":
                            thinking_blocks.append(value.get("thinking", ""))
                        # Also check for reasoning_content in value
                        elif value.get("reasoning_content"):
                            thinking_blocks.append(
                                str(value.get("reasoning_content", ""))
                            )

                    # Also check if non_standard block has thinking directly
                    if block.get("thinking"):
                        thinking_blocks.append(block.get("thinking", ""))

        thinking = "".join(thinking_blocks)

    # 2. reasoning_content attribute (DeepSeek-R1 style)
    if not thinking:
        reasoning_attr = getattr(message, "reasoning_content", None)
        if reasoning_attr:
            if isinstance(reasoning_attr, str):
                thinking = reasoning_attr
            elif isinstance(reasoning_attr, list):
                thinking = "".join(str(p) for p in reasoning_attr if isinstance(p, str))

    # 3. Check additional_kwargs for thinking content (multiple keys)
    if not thinking:
        additional_kwargs = getattr(message, "additional_kwargs", {}) or {}
        # Check various keys that might contain thinking/reasoning
        for key in ["thinking", "reasoning_content", "reasoning"]:
            if key in additional_kwargs:
                value = additional_kwargs[key]
                if isinstance(value, str) and value:
                    thinking = value
                    break
                elif isinstance(value, list):
                    joined = "".join(str(p) for p in value if isinstance(p, str))
                    if joined:
                        thinking = joined
                        break

    return thinking.strip()
