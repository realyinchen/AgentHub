"""Navigator agent with Amap (高德地图) capabilities.

This module implements a ReAct agent using pure LangGraph (StateGraph).
The agent dynamically selects LLM based on thinking_mode from config.
"""

from typing import Literal

from langchain_core.messages import AIMessage, BaseMessage, SystemMessage, ToolMessage
from langchain_core.tools import BaseTool
from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import MessagesState

from app.core.models import get_llm
from app.prompt.navigator import get_navigator_prompt
from app.tools.amap import AMAP_TOOLS
from app.tools.time import get_current_time
from app.tools.web import create_web_search


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
    supported_input_types = {'text', 'image_url', 'video_url', 'video'}
    
    # Filter out unsupported types (like 'thinking')
    filtered_content = []
    for block in message.content:
        if isinstance(block, str):
            # Plain string is always supported
            filtered_content.append(block)
        elif isinstance(block, dict):
            block_type = block.get('type', 'text')
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
    - Amap tools for location and routing
    - Time tool for current time
    - Web search tool for weather information
    """
    # Amap tools
    tools = list(AMAP_TOOLS)
    
    # Add time tool
    tools.append(get_current_time)
    
    # Add web search tool for weather queries
    web_search = create_web_search(max_results=3)
    if web_search:
        tools.append(web_search)
    
    return tools


def _get_tools_by_name(tools: list[BaseTool]) -> dict[str, BaseTool]:
    """Create a lookup dictionary for tools by name."""
    return {tool.name: tool for tool in tools}


# Get system prompt
system_prompt = get_navigator_prompt()


async def llm_call(state: NavigatorState, config: RunnableConfig) -> dict:
    """LLM decides whether to call a tool or not.

    This node:
    1. Gets thinking_mode from config
    2. Selects appropriate LLM (normal or thinking)
    3. Binds tools to the LLM
    4. Invokes the LLM with messages

    Args:
        state: Current graph state containing messages
        config: Runnable config with thinking_mode in configurable

    Returns:
        dict: Updated state with new message from LLM
    """
    # Get thinking_mode from config
    thinking_mode = config.get("configurable", {}).get("thinking_mode", False)
    
    # Get the appropriate LLM based on thinking_mode
    llm = get_llm(thinking_mode=thinking_mode)

    # Get tools
    tools = _get_tools()

    # Bind tools to the LLM
    llm_with_tools = llm.bind_tools(tools) # type: ignore

    # Get messages from state
    messages = state.get("messages", [])

    # Filter messages to remove 'thinking' type content blocks
    # 'thinking' is an OUTPUT format, not an INPUT format for any LLM
    filtered_messages = [
        _filter_message_content_for_model(msg)
        for msg in messages
    ]

    # Build the full message list with system prompt
    full_messages = [SystemMessage(content=system_prompt)] + filtered_messages

    # Use astream for streaming support
    # Collect and accumulate all chunks to build the final response
    final_chunk = None
    async for chunk in llm_with_tools.astream(full_messages):
        if final_chunk is None:
            final_chunk = chunk
        else:
            # Accumulate chunks (AIMessageChunk supports + operator)
            final_chunk = final_chunk + chunk
    
    # If we got a response, return it
    if final_chunk:
        return {"messages": [final_chunk]}
    
    # Fallback to ainvoke if streaming produced no output
    response = await llm_with_tools.ainvoke(full_messages)
    return {"messages": [response]}


async def tool_node(state: NavigatorState) -> dict:
    """Execute tools requested by the LLM.

    This node:
    1. Gets the last message (should be an AIMessage with tool_calls)
    2. Executes each tool call
    3. Returns ToolMessages with results

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

    # Execute each tool call
    tool_messages = []
    for tool_call in tool_calls:
        tool_name = tool_call.get("name")
        tool_args = tool_call.get("args", {})
        tool_call_id = tool_call.get("id")

        # Get the tool by name
        tool = tools_by_name.get(tool_name)

        if tool:
            try:
                # Execute the tool (async)
                result = await tool.ainvoke(tool_args)
                if isinstance(result, str):
                    observation = result
                else:
                    observation = str(result)
            except Exception as e:
                observation = f"Error executing tool {tool_name}: {str(e)}"
        else:
            observation = f"Tool {tool_name} not found"

        # Create ToolMessage
        tool_messages.append(
            ToolMessage(content=observation, tool_call_id=tool_call_id)
        )

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