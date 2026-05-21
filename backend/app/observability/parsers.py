"""
Pure parsing utilities for LangChain message content extraction.

All functions are stateless and side-effect-free, making them easy to test
and reuse across the observability layer.
"""

from typing import Any, Optional

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage

from app.utils.message_utils import convert_message_content_to_string
from app.schemas.trace import (
    AIStepMetadata,
    CheckpointInfo,
    StepOutput,
    ToolStepMetadata,
)


def extract_thinking(message: AIMessage) -> str:
    """Extract thinking/reasoning content from an AI message.

    Checks three sources in order:
    1. Structured content blocks (type="thinking")
    2. ``reasoning_content`` attribute (DeepSeek-R1 style)
    3. ``additional_kwargs["reasoning_content"]``
    """
    thinking = ""

    # 1. Structured content (DashScope thinking models)
    if isinstance(message.content, list):
        thinking_blocks: list[str] = []
        for block in message.content:
            if isinstance(block, dict) and block.get("type") == "thinking":
                content = block.get("thinking", "")
                if content:
                    thinking_blocks.append(content)
        thinking = "".join(thinking_blocks)

    # 2. reasoning_content attribute (DeepSeek-R1 style)
    if not thinking:
        reasoning_attr = getattr(message, "reasoning_content", None)
        if reasoning_attr:
            if isinstance(reasoning_attr, str):
                thinking = reasoning_attr
            elif isinstance(reasoning_attr, list):
                thinking = "".join(str(p) for p in reasoning_attr if isinstance(p, str))

    # 3. additional_kwargs
    if not thinking:
        reasoning_from_kwargs = message.additional_kwargs.get("reasoning_content", "")
        if reasoning_from_kwargs:
            thinking = reasoning_from_kwargs

    return thinking.strip()


def get_tool_args(tool_message: ToolMessage, all_messages: list[BaseMessage]) -> dict:
    """Find the tool call args from the AIMessage that invoked this tool.

    Searches backwards through ``all_messages`` for an AIMessage whose
    ``tool_calls`` list contains an entry matching ``tool_message.tool_call_id``.
    """
    tool_call_id = getattr(tool_message, "tool_call_id", None)
    if not tool_call_id:
        return {}

    for msg in reversed(all_messages):
        if isinstance(msg, AIMessage) and msg.tool_calls:
            for tc in msg.tool_calls:
                if tc.get("id") == tool_call_id:
                    return tc.get("args", {})
    return {}


def extract_step_from_checkpoint(
    checkpoint: CheckpointInfo,
    state: Any,
    step_number: int,
) -> Optional[StepOutput]:
    """Convert a checkpoint state snapshot into a :class:`StepOutput`.

    This is the main entry point for checkpoint → step conversion.
    It delegates to :func:`convert_message_content_to_string`, :func:`extract_thinking`,
    and :func:`get_tool_args` for the heavy lifting.
    """
    channel_values = state.values
    messages: list[BaseMessage] = channel_values.get("messages", [])

    if not messages:
        return None

    last_message = messages[-1]

    # Determine message type and content
    if isinstance(last_message, HumanMessage):
        message_type = "human"
        content = convert_message_content_to_string(last_message.content)
    elif isinstance(last_message, AIMessage):
        message_type = "ai"
        content = convert_message_content_to_string(last_message.content)
    elif isinstance(last_message, ToolMessage):
        message_type = "tool"
        content = convert_message_content_to_string(last_message.content)
    else:
        message_type = "unknown"
        content = str(last_message.content) if hasattr(last_message, "content") else ""

    # Extract message ID
    message_id = getattr(last_message, "id", None) or getattr(
        last_message, "tool_call_id", None
    )

    # Build step output
    step = StepOutput(
        step_number=step_number,
        message_type=message_type,
        content=content,
        timestamp=checkpoint.timestamp,
        message_id=str(message_id) if message_id else None,
        checkpoint_id=checkpoint.checkpoint_id,
        node_name=checkpoint.node_name,
        ai_metadata=None,
        tool_metadata=None,
    )

    # AI-specific metadata
    if isinstance(last_message, AIMessage):
        thinking = extract_thinking(last_message)
        tool_calls = getattr(last_message, "tool_calls", None)

        step.ai_metadata = AIStepMetadata(
            thinking=thinking if thinking else None,
            tool_calls=tool_calls if tool_calls else None,
            model_name=(
                last_message.response_metadata.get("model_name")
                if hasattr(last_message, "response_metadata")
                and isinstance(last_message.response_metadata, dict)
                else None
            ),
        )

    # Tool-specific metadata
    if isinstance(last_message, ToolMessage):
        step.tool_metadata = ToolStepMetadata(
            tool_name=getattr(last_message, "name", None) or "",
            tool_args=get_tool_args(last_message, messages),
            tool_call_id=getattr(last_message, "tool_call_id", None),
        )

    return step
