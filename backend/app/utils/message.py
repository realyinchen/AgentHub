"""Message utilities — conversion, extraction, and parsing.

Pure functions for LangChain message handling. No business logic,
no database dependencies.
"""

import logging
from collections.abc import Sequence
from typing import Any

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage

from app.schemas.chat import ChatMessage, ToolCall
from app.schemas.trace import (
    AIStepMetadata,
    CheckpointInfo,
    StepOutput,
    ToolStepMetadata,
)

logger = logging.getLogger(__name__)


# =============================================================================
# Token utilities
# =============================================================================


def empty_totals() -> dict[str, int]:
    """Return a zero-filled token totals dictionary."""
    return {
        "input_tokens": 0,
        "output_tokens": 0,
        "total_tokens": 0,
    }


def extract_usage(final_message: Any) -> dict | None:
    """Extract token usage from a finalized AI message.

    Tries ``usage_metadata`` first (preferred), then falls back to
    ``response_metadata.token_usage`` or ``response_metadata.usage``.
    """
    if final_message is None:
        return None

    # 1. Try usage_metadata (standard LangChain format)
    usage = getattr(final_message, "usage_metadata", None)
    if usage:
        return dict(usage)

    # 2. Try response_metadata (OpenAI/LiteLLM format)
    resp_meta = getattr(final_message, "response_metadata", None)
    if resp_meta and isinstance(resp_meta, dict):
        # OpenAI style: token_usage
        token_usage = resp_meta.get("token_usage")
        if token_usage:
            return {
                "input_tokens": token_usage.get("prompt_tokens", 0),
                "output_tokens": token_usage.get("completion_tokens", 0),
                "total_tokens": token_usage.get("total_tokens", 0),
            }
        # LiteLLM style: usage object
        usage_obj = resp_meta.get("usage")
        if usage_obj and isinstance(usage_obj, dict):
            return {
                "input_tokens": usage_obj.get("prompt_tokens", 0),
                "output_tokens": usage_obj.get("completion_tokens", 0),
                "total_tokens": usage_obj.get("total_tokens", 0),
            }

    # 3. Try additional_kwargs.usage (some providers)
    additional_kwargs = getattr(final_message, "additional_kwargs", None)
    if additional_kwargs and isinstance(additional_kwargs, dict):
        usage_kwarg = additional_kwargs.get("usage")
        if usage_kwarg and isinstance(usage_kwarg, dict):
            return {
                "input_tokens": usage_kwarg.get("prompt_tokens", 0),
                "output_tokens": usage_kwarg.get("completion_tokens", 0),
                "total_tokens": usage_kwarg.get("total_tokens", 0),
            }

    return None


def accumulate_usage(totals: dict[str, int], usage: dict) -> None:
    """Accumulate per-call *usage* into running *totals* (mutated in-place)."""
    totals["input_tokens"] += usage.get("input_tokens", 0)
    totals["output_tokens"] += usage.get("output_tokens", 0)
    totals["total_tokens"] += usage.get("total_tokens", 0)


# =============================================================================
# Content conversion
# =============================================================================


def convert_message_content_to_string(content: str | list[str | dict]) -> str:
    """Convert message content to string.

    Handles both string and structured content formats.
    """
    if isinstance(content, str):
        return content
    text: list[str] = []
    for content_item in content:
        if isinstance(content_item, str):
            text.append(content_item)
            continue
        if isinstance(content_item, dict) and content_item.get("type") == "text":
            text.append(content_item.get("text", ""))
    return "".join(text)


# =============================================================================
# Thinking/reasoning extraction
# =============================================================================


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


# =============================================================================
# Message conversion
# =============================================================================


def langchain_to_chat_message(message: BaseMessage) -> ChatMessage:
    """Create a ChatMessage from a LangChain message.

    Handles HumanMessage, AIMessage, and ToolMessage.
    """
    match message:
        case HumanMessage():
            human_message = ChatMessage(
                type="human",
                content=convert_message_content_to_string(message.content),
            )
            # Restore custom_data from additional_kwargs (for quote feature persistence)
            if message.additional_kwargs.get("custom_data"):
                human_message.custom_data = message.additional_kwargs["custom_data"]
            return human_message
        case AIMessage():
            ai_message = ChatMessage(
                type="ai",
                content=convert_message_content_to_string(message.content),
            )
            if message.tool_calls:
                # Convert LangChain tool_calls to our ToolCall schema
                ai_message.tool_calls = [
                    ToolCall(
                        name=tc.get("name", ""),
                        args=tc.get("args", {}),
                        id=tc.get("id"),
                    )
                    for tc in message.tool_calls
                ]
            if message.response_metadata:
                ai_message.response_metadata = message.response_metadata

            custom_data = message.additional_kwargs.get("custom_data")
            if isinstance(custom_data, dict):
                ai_message.custom_data.update(custom_data)

            # Extract and save thinking content to custom_data
            thinking_content = extract_thinking(message)
            if thinking_content:
                ai_message.custom_data["thinking"] = thinking_content

            return ai_message
        case ToolMessage():
            tool_message = ChatMessage(
                type="tool",
                content=convert_message_content_to_string(message.content),
                tool_call_id=message.tool_call_id,
                name=getattr(message, "name", None),
            )
            return tool_message
        case _:
            raise ValueError(f"Unsupported message type: {message.__class__.__name__}")


# =============================================================================
# Tool info extraction
# =============================================================================


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


def messages_to_tool_info(messages: list[BaseMessage]) -> list[dict]:
    """Extract tool call information from a list of messages.

    This function processes AI messages with tool calls and their corresponding
    Tool messages, returning a list of tool info with name, args, output, and order.

    Returns:
        list[dict]: List of tool info dicts with keys: name, id, args, output, order
    """
    tool_info_list = []
    tool_call_order = 0

    # Build a map of tool_call_id -> ToolMessage content
    tool_results: dict[str, str] = {}
    for msg in messages:
        if isinstance(msg, ToolMessage):
            tool_results[msg.tool_call_id] = convert_message_content_to_string(
                msg.content
            )

    # Process AI messages to extract tool calls with their results
    for msg in messages:
        if isinstance(msg, AIMessage) and msg.tool_calls:
            for tool_call in msg.tool_calls:
                tool_call_id = tool_call.get("id") or ""
                tool_info = {
                    "name": tool_call.get("name") or "unknown",
                    "id": tool_call_id,
                    "args": tool_call.get("args") or {},
                    "output": tool_results.get(tool_call_id) if tool_call_id else None,
                    "order": tool_call_order,
                }
                tool_info_list.append(tool_info)
                tool_call_order += 1

    return tool_info_list


def collect_tool_calls_for_final_response(
    messages: Sequence[BaseMessage], ai_message_index: int
) -> list[dict]:
    """Collect tool call information for a final AI message at a given index.

    This function extracts all tool calls from the conversation up to the specified
    AI message index, pairing each tool call with its result for display in the final response.

    Args:
        messages: The complete list of messages in the conversation
        ai_message_index: The index of the AI message in the messages list

    Returns:
        list[dict]: List of tool info dicts with keys: name, id, args, output, order
    """
    tool_info_list = []
    tool_call_order = 0

    # Build a map of tool_call_id -> ToolMessage content
    tool_results: dict[str, str] = {}
    for msg in messages:
        if isinstance(msg, ToolMessage):
            tool_results[msg.tool_call_id] = convert_message_content_to_string(
                msg.content
            )

    # Collect all tool calls up to (but not including) the specified AI message
    for i, msg in enumerate(list(messages)[:ai_message_index]):
        if isinstance(msg, AIMessage) and msg.tool_calls:
            for tool_call in msg.tool_calls:
                tool_call_id = tool_call.get("id") or ""
                tool_info = {
                    "name": tool_call.get("name") or "unknown",
                    "id": tool_call_id,
                    "args": tool_call.get("args") or {},
                    "output": tool_results.get(tool_call_id) if tool_call_id else None,
                    "order": tool_call_order,
                }
                tool_info_list.append(tool_info)
                tool_call_order += 1

    return tool_info_list


def augment_ai_message_with_tool_info(messages: list[BaseMessage]) -> list[BaseMessage]:
    """Augment AI messages with tool info in custom_data.

    This function adds tool_info to the last AI message's custom_data,
    containing all tool calls from the conversation with their results.

    Returns:
        list[BaseMessage]: The messages list with augmented AI messages
    """
    tool_info = messages_to_tool_info(messages)

    if not tool_info:
        return messages

    # Find the last AI message and add tool_info to its additional_kwargs
    for i in range(len(messages) - 1, -1, -1):
        msg = messages[i]
        if isinstance(msg, AIMessage):
            # Use additional_kwargs instead of custom_data (which doesn't exist on AIMessage)
            if not msg.additional_kwargs:
                msg.additional_kwargs = {}
            msg.additional_kwargs["tool_info"] = tool_info
            break

    return messages


# =============================================================================
# Checkpoint → Step conversion
# =============================================================================


def extract_step_from_checkpoint(
    checkpoint: CheckpointInfo,
    state: Any,
    step_number: int,
) -> StepOutput | None:
    """Convert a checkpoint state snapshot into a :class:`StepOutput`.

    This is the main entry point for checkpoint → step conversion.
    It delegates to other functions in this module for the heavy lifting.
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
