"""Navigator agent with Amap (Gaode Map) capabilities.

This module implements a ReAct agent using pure LangGraph (StateGraph).
The agent uses the reusable llm_streaming module for token tracking.
Tools are executed in parallel using asyncio.gather for optimal performance.
"""

import asyncio
from typing import Literal

from langchain_core.messages import AIMessage, BaseMessage, SystemMessage, ToolMessage
from langchain_core.tools import BaseTool
from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import MessagesState

from app.utils.llm import get_chat_litellm
from app.core.model_manager import ModelManager
from app.prompt.navigator import get_navigator_prompt
from app.tools.amap import AMAP_TOOLS
from app.tools.time import get_current_time


class NavigatorState(MessagesState):
    """State for navigator agent.

    Inherits from MessagesState which provides:
        messages: list[BaseMessage] - conversation history
    """

    pass


def _filter_message_content_for_model(message: BaseMessage) -> BaseMessage:
    """Filter message content to only include types supported for LLM input.

    When a thinking model outputs 'thinking' type content blocks, these are
    OUTPUT formats, not INPUT formats. Even thinking models cannot accept
    'thinking' type blocks as INPUT in subsequent messages.

    This function removes 'thinking' type blocks from all messages before
    sending them to any LLM, regardless of thinking_mode.

    Args:
        message: The message to filter

    Returns:
        The filtered message (modified in place for efficiency)
    """
    # Only filter AIMessage with structured content (list of blocks)
    if not isinstance(message, AIMessage):
        return message

    if not isinstance(message.content, list):
        return message

    # Supported content types for LLM INPUT (not output)
    # Note: 'thinking' is an OUTPUT type, not an INPUT type
    supported_input_types = {"text", "image_url", "video_url", "video"}

    # Filter out unsupported types (like 'thinking')
    filtered_content = []
    for block in message.content:
        if isinstance(block, str):
            # Plain string is always supported
            filtered_content.append(block)
        elif isinstance(block, dict):
            block_type = block.get("type", "text")
            if block_type in supported_input_types:
                filtered_content.append(block)

    # Update the message content
    if filtered_content:
        message.content = filtered_content
    else:
        # If all content was filtered, set to empty string
        message.content = ""

    return message


def _get_tools() -> list[BaseTool]:
    """Get tools for navigator agent.

    Tools include:
    - Amap tools for location, routing, and weather
    - Time tool for current time
    """
    # Amap tools (includes amap_weather for weather queries)
    tools = list(AMAP_TOOLS)

    # Add time tool
    tools.append(get_current_time)

    return tools


def _get_tools_by_name(tools: list[BaseTool]) -> dict[str, BaseTool]:
    """Create a lookup dictionary for tools by name."""
    return {tool.name: tool for tool in tools}


# Get system prompt
system_prompt = get_navigator_prompt()


async def llm_call(state: NavigatorState, config: RunnableConfig) -> dict:
    """LLM decides whether to call a tool or not.

    This node:
    1. Gets thinking_mode and model_name from config
    2. Calls LLM using ChatLiteLLM with TRUE streaming (astream)
    3. Collects content, tool_calls, and usage_metadata from stream
    4. Returns the response as AIMessage

    Args:
        state: Current graph state containing messages
        config: Runnable config with thinking_mode and model_name in configurable

    Returns:
        dict: Updated state with new message from LLM
    """
    # Get thinking_mode and model_name from config
    configurable = config.get("configurable", {})
    thinking_mode = configurable.get("thinking_mode", False)
    model_name = configurable.get("model_name")

    # Get default model if not specified
    if not model_name:
        model_name = ModelManager.get_default_llm_id()

    if not model_name:
        raise ValueError("No model available for navigator")

    # Get tools
    tools = _get_tools()

    # Get messages from state
    messages = state.get("messages", [])

    # Filter messages to remove 'thinking' type content blocks
    # 'thinking' is an OUTPUT format, not an INPUT format for any LLM
    filtered_messages = [_filter_message_content_for_model(msg) for msg in messages]

    # Build the full message list with system prompt
    full_messages = [SystemMessage(content=system_prompt)] + filtered_messages

    # Get ChatLiteLLM instance (configured for true streaming)
    llm = get_chat_litellm(
        model=model_name,
        thinking_mode=thinking_mode,
        tools=tools,
    )

    # ============== TRUE STREAMING with astream ==============
    # Unlike ainvoke (one-shot), astream yields chunks as they arrive
    # This enables real token-by-token streaming and stable usage_metadata
    full_content = ""
    usage_metadata = None  # Can be dict or UsageMetadata object
    tool_calls_list: list[dict] = []
    reasoning_content = ""

    async for chunk in llm.astream(full_messages, config=config):
        # 1. Collect content (string or structured)
        if chunk.content:
            if isinstance(chunk.content, str):
                full_content += chunk.content
            elif isinstance(chunk.content, list):
                # Handle structured content (DashScope thinking models)
                for block in chunk.content:
                    if isinstance(block, dict):
                        block_type = block.get("type")
                        if block_type == "text":
                            text = block.get("text", "")
                            if text:
                                full_content += text
                        elif block_type == "thinking":
                            thinking = block.get("thinking", "")
                            if thinking:
                                reasoning_content += thinking

        # 2. Collect tool_calls (Agent functionality)
        # Convert ToolCall objects to dict format for AIMessage
        if hasattr(chunk, "tool_calls") and chunk.tool_calls:
            for tc in chunk.tool_calls:
                tool_calls_list.append(
                    {
                        "id": tc.get("id", "")
                        if isinstance(tc, dict)
                        else getattr(tc, "id", ""),
                        "name": tc.get("name", "")
                        if isinstance(tc, dict)
                        else getattr(tc, "name", ""),
                        "args": tc.get("args", {})
                        if isinstance(tc, dict)
                        else getattr(tc, "args", {}),
                        "type": "tool_call",
                    }
                )

        # 3. Capture usage_metadata (usually in the last chunk)
        if hasattr(chunk, "usage_metadata") and chunk.usage_metadata is not None:
            usage_metadata = chunk.usage_metadata
        # Fallback: try response_metadata for token usage
        elif hasattr(chunk, "response_metadata") and chunk.response_metadata:
            resp_meta = chunk.response_metadata
            if "token_usage" in resp_meta:
                token_usage = resp_meta["token_usage"]
                usage_metadata = {
                    "input_tokens": token_usage.get("prompt_tokens", 0),
                    "output_tokens": token_usage.get("completion_tokens", 0),
                    "total_tokens": token_usage.get("total_tokens", 0),
                }

    # Build the final AIMessage
    ai_message = AIMessage(
        content=full_content,
        tool_calls=tool_calls_list,
        usage_metadata=usage_metadata,
    )

    # Add reasoning_content to additional_kwargs if present
    if reasoning_content:
        ai_message.additional_kwargs["reasoning_content"] = reasoning_content

    # Return the AIMessage for LangGraph compatibility
    return {"messages": [ai_message]}


async def tool_node(state: NavigatorState) -> dict:
    """Execute tools requested by the LLM in parallel.

    This node:
    1. Gets the last message (should be an AIMessage with tool_calls)
    2. Executes all tool calls simultaneously using asyncio.gather
    3. Returns ToolMessages with results

    Using asyncio.gather with return_exceptions=True ensures:
    - All tools start at the same time (true parallelism)
    - One tool failure doesn't affect others
    - Maximum performance for multi-tool scenarios

    Args:
        state: Current graph state

    Returns:
        dict: Updated state with tool results
    """
    messages = state.get("messages", [])
    last_message = messages[-1]

    # Get tool calls from the last message
    tool_calls = getattr(last_message, "tool_calls", [])

    # Get tools
    tools = _get_tools()
    tools_by_name = _get_tools_by_name(tools)

    async def execute_single_call(tool_call: dict) -> ToolMessage:
        """Execute a single tool call and return the result as ToolMessage.

        Args:
            tool_call: Tool call dict with 'name', 'args', and 'id' keys

        Returns:
            ToolMessage with the tool result or error message
        """
        tool_name = tool_call.get("name", "")
        tool_args = tool_call.get("args", {})
        tool_call_id = tool_call.get("id", "unknown")

        # Get the tool by name
        tool = tools_by_name.get(tool_name)

        if not tool:
            return ToolMessage(
                content=f"Tool {tool_name} not found", tool_call_id=tool_call_id
            )

        try:
            # Execute the tool (async)
            result = await tool.ainvoke(tool_args)
            observation = result if isinstance(result, str) else str(result)
        except Exception as e:
            observation = f"Error executing tool {tool_name}: {str(e)}"

        return ToolMessage(content=observation, tool_call_id=tool_call_id)

    # Execute all tool calls in parallel using asyncio.gather
    # return_exceptions=True ensures one failure doesn't crash others
    results = await asyncio.gather(
        *[execute_single_call(tc) for tc in tool_calls], return_exceptions=True
    )

    # Process results and handle any unexpected exceptions
    tool_messages = []
    for result in results:
        if isinstance(result, Exception):
            # This shouldn't happen since execute_single_call catches exceptions,
            # but handle it just in case
            tool_messages.append(
                ToolMessage(
                    content=f"Unexpected error: {str(result)}", tool_call_id="unknown"
                )
            )
        else:
            tool_messages.append(result)

    return {"messages": tool_messages}


def should_continue(state: NavigatorState) -> Literal["tools", "__end__"]:
    """Decide if we should continue the loop or stop.

    If the LLM made tool calls, route to the tool node.
    Otherwise, end the graph execution.

    Args:
        state: Current graph state

    Returns:
        Literal["tools", "__end__"]: Next node to visit
    """
    messages = state.get("messages", [])
    last_message = messages[-1]

    # Check if the last message has tool calls
    tool_calls = getattr(last_message, "tool_calls", None)

    if tool_calls:
        return "tools"

    # Otherwise, we stop (reply to the user)
    return "__end__"


# Build the graph
workflow = StateGraph(NavigatorState)

# Add nodes
workflow.add_node("llm_call", llm_call)
workflow.add_node("tools", tool_node)

# Add edges
workflow.add_edge(START, "llm_call")
workflow.add_conditional_edges("llm_call", should_continue, ["tools", END])
workflow.add_edge("tools", "llm_call")

# Compile the agent
navigator = workflow.compile()
