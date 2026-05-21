import logging
from collections.abc import Sequence
from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    ToolMessage,
)

from app.schemas.chat import ChatMessage, ToolCall


logger = logging.getLogger(__name__)


def convert_message_content_to_string(content: str | list[str | dict]) -> str:
    if isinstance(content, str):
        return content
    text: list[str] = []
    for content_item in content:
        if isinstance(content_item, str):
            text.append(content_item)
            continue
        if content_item["type"] == "text":
            text.append(content_item["text"])
    return "".join(text)


def _extract_thinking_content(message: AIMessage) -> str:
    """
    Extract thinking/reasoning content from an AIMessage.

    Handles multiple formats:
    1. Structured content: [{"type": "thinking", "thinking": "..."}, ...]
    2. reasoning_content attribute (DeepSeek-R1 style)
    3. additional_kwargs.reasoning_content

    Returns:
        str: Extracted thinking content, or empty string if none found
    """
    thinking = ""

    # 1. Check structured content (DashScope thinking models)
    if isinstance(message.content, list):
        thinking_blocks = []
        for block in message.content:
            if isinstance(block, dict) and block.get("type") == "thinking":
                content = block.get("thinking", "")
                if content:
                    thinking_blocks.append(content)
        # Join thinking blocks directly without adding newlines
        # Each block is already a chunk of the streaming output
        thinking = "".join(thinking_blocks)

    # 2. Check reasoning_content attribute (DeepSeek-R1 style)
    if not thinking:
        reasoning_attr = getattr(message, "reasoning_content", None)
        if reasoning_attr:
            if isinstance(reasoning_attr, str):
                thinking = reasoning_attr
            elif isinstance(reasoning_attr, list):
                thinking = convert_message_content_to_string(reasoning_attr)

    # 3. Check additional_kwargs for reasoning_content
    if not thinking:
        reasoning_from_kwargs = message.additional_kwargs.get("reasoning_content", "")
        if reasoning_from_kwargs:
            thinking = reasoning_from_kwargs

    return thinking.strip()


def langchain_to_chat_message(message: BaseMessage) -> ChatMessage:
    """Create a ChatMessage from a LangChain message."""
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

            # Extract and save thinking content to custom_data
            thinking_content = _extract_thinking_content(message)
            if thinking_content:
                ai_message.custom_data["thinking"] = thinking_content

            return ai_message
        case ToolMessage():
            tool_message = ChatMessage(
                type="tool",
                content=convert_message_content_to_string(message.content),
                tool_call_id=message.tool_call_id,
                name=getattr(message, "name", None),  # Tool name if available
            )
            return tool_message
        case _:
            raise ValueError(f"Unsupported message type: {message.__class__.__name__}")


def messages_to_tool_info(messages: list[BaseMessage]) -> list[dict]:
    """
    Extract tool call information from a list of messages.

    This function processes AI messages with tool calls and their corresponding Tool messages,
    returning a list of tool info with name, args, output, and order.

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
    """
    Collect tool call information for a final AI message at a given index.

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
    """
    Augment AI messages with tool info in custom_data.

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
