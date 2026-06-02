"""
Execution DAG builder for LangGraph agent traces.

Provides :class:`DagBuilder` which converts a conversation's messages
into a directed acyclic graph suitable for visualization.

Each message (Human, AI, Tool) becomes a node, with edges connecting
messages in chronological order to show the conversation flow.
"""

from langchain_core.messages import HumanMessage, AIMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from langgraph.graph.state import CompiledStateGraph

from app.schemas.trace import AIStepMetadata, DagNode, ExecutionDag, StepOutput, ToolStepMetadata


class DagBuilder:
    """Build execution DAGs from LangGraph agent state."""

    def __init__(self, agent: CompiledStateGraph):
        self.agent = agent

    async def get_execution_dag(self, thread_id: str) -> ExecutionDag:
        """Build the execution DAG for a thread.

        Constructs a message-flow DAG where each node represents a message
        (Human, AI, or Tool) in the conversation. Edges connect messages in
        chronological order.

        Args:
            thread_id: The thread ID.

        Returns:
            Execution DAG with nodes and edges representing the message flow.
        """
        # Get final state
        config: RunnableConfig = {"configurable": {"thread_id": thread_id}}
        state = await self.agent.aget_state(config)
        messages: list = state.values.get("messages", [])

        # Build DAG from messages
        nodes: list[DagNode] = []
        edges: list[tuple[str, str]] = []

        for i, msg in enumerate(messages):
            step_number = i + 1

            # Determine message_type for our schema
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
                timestamp=None,
                message_id=getattr(msg, "id", None),
                checkpoint_id=None,
                node_name=None,
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

            node = DagNode(
                node_id=node_id,
                step_number=step_number,
                node_name=message_type,
                title=title,
                message_type=message_type,
                step=step,
            )
            nodes.append(node)

            # Edge: previous node → current node
            if i > 0:
                prev_node_id = f"node_{i}"
                edges.append((prev_node_id, node_id))

        return ExecutionDag(
            thread_id=thread_id,
            nodes=nodes,
            edges=edges,
            total_steps=len(messages),
            steps=[n.step for n in nodes],
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