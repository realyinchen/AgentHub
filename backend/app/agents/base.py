"""Base agent infrastructure for building ReAct agents.

This module provides reusable components for building standard ReAct agents:
- Message filtering for LLM input compatibility
- LLM call node with true streaming and token tracking
- Tool execution node (with optional parallel execution)
- Conditional edge router
- Graph builder factory function
- AgentRegistry for self-registration via decorators

All new agents should use build_standard_agent_graph() to minimize code duplication.
"""

import logging
from typing import Any, Callable, Literal

from langchain_core.messages import AIMessage, BaseMessage, SystemMessage, ToolMessage
from langchain_core.tools import BaseTool
from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import MessagesState
from langgraph.graph.state import CompiledStateGraph

from app.utils.llm import get_chat_litellm
from app.core.model_manager import ModelManager


logger = logging.getLogger(__name__)


class AgentState(MessagesState):
    """Standard state for all ReAct agents.

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
                # For 'text' type, extract just the text string
                # DashScope expects plain string content, not {"type": "text", "text": "..."}
                if block_type == "text":
                    text_content = block.get("text", "")
                    if text_content:
                        filtered_content.append(text_content)
                else:
                    # Keep other supported types as-is (image_url, video_url, video)
                    filtered_content.append(block)

    # Update the message content
    # IMPORTANT: Convert to plain string if all content is text
    # DashScope doesn't accept list of strings for message content
    if filtered_content:
        # Check if all content is plain string
        if all(isinstance(item, str) for item in filtered_content):
            # Join all text content into a single string
            message.content = "".join(filtered_content)
        else:
            message.content = filtered_content
    else:
        # If all content was filtered, set to empty string
        message.content = ""

    return message


def _get_tools_by_name(tools: list[BaseTool]) -> dict[str, BaseTool]:
    """Create a lookup dictionary for tools by name."""
    return {tool.name: tool for tool in tools}


def create_llm_call_node(
    system_prompt: str,
    get_tools_fn: Callable[[], list[BaseTool]],
) -> Callable[..., Any]:
    """Create a reusable llm_call node function.

    Args:
        system_prompt: The system prompt to prepend to messages
        get_tools_fn: Callable that returns the list of tools for this agent

    Returns:
        The llm_call async function for use in StateGraph
    """

    async def llm_call(state: AgentState, config: RunnableConfig) -> dict:
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
            raise ValueError("No model available for agent")

        # Get tools lazily
        tools = get_tools_fn()

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

    return llm_call


def create_tool_node(
    get_tools_fn: Callable[[], list[BaseTool]],
    parallel: bool = True,
) -> Callable[..., Any]:
    """Create a reusable tool execution node function.

    Args:
        get_tools_fn: Callable that returns the list of tools for this agent
        parallel: If True, execute multiple tools in parallel using asyncio.gather

    Returns:
        The tool_node async function for use in StateGraph
    """

    async def tool_node(state: AgentState) -> dict:
        """Execute tools requested by the LLM.

        This node:
        1. Gets the last message (should be an AIMessage with tool_calls)
        2. Executes each tool call (in parallel if enabled)
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

        if not tool_calls:
            return {"messages": []}

        # Get tools lazily
        tools = get_tools_fn()
        tools_by_name = _get_tools_by_name(tools)

        async def execute_single_tool(tool_call: dict) -> ToolMessage:
            """Execute a single tool call and return a ToolMessage."""
            tool_name = tool_call.get("name", "")
            tool_args = tool_call.get("args", {})
            tool_call_id = tool_call.get("id", "")

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
            return ToolMessage(content=observation, tool_call_id=tool_call_id)

        if parallel and len(tool_calls) > 1:
            # Execute multiple tools in parallel
            import asyncio

            tool_messages = await asyncio.gather(
                *[execute_single_tool(tc) for tc in tool_calls]
            )
        else:
            # Execute sequentially (single tool or parallel=False)
            tool_messages = [await execute_single_tool(tc) for tc in tool_calls]

        return {"messages": tool_messages}

    return tool_node


def should_continue(state: AgentState) -> Literal["tools", "__end__"]:
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


class AgentRegistry:
    """Registry for all compiled agent graphs.

    Agents self-register via the @register_agent decorator.
    This eliminates the need to manually maintain agent_map in agent_utils.py.

    Example:
        @register_agent("chatbot")
        chatbot = workflow.compile()
    """

    _agents: dict[str, CompiledStateGraph] = {}

    @classmethod
    def register(cls, agent_id: str, agent: CompiledStateGraph) -> None:
        """Register a compiled agent graph."""
        cls._agents[agent_id] = agent
        logger.info(f"Agent registered: {agent_id}")

    @classmethod
    def get(cls, agent_id: str) -> CompiledStateGraph | None:
        """Get an agent by ID."""
        return cls._agents.get(agent_id)

    @classmethod
    def get_all_ids(cls) -> list[str]:
        """Get all registered agent IDs."""
        return list(cls._agents.keys())

    @classmethod
    def get_all(cls) -> dict[str, CompiledStateGraph]:
        """Get all registered agents."""
        return dict(cls._agents)


def register_agent(agent_id: str) -> Callable[[CompiledStateGraph], CompiledStateGraph]:
    """Decorator to register a compiled agent graph.

    Args:
        agent_id: Unique identifier for the agent (e.g., "chatbot", "navigator")

    Returns:
        Decorator that registers the agent and returns it unchanged

    Example:
        @register_agent("chatbot")
        chatbot = workflow.compile()
    """

    def decorator(agent: CompiledStateGraph) -> CompiledStateGraph:
        AgentRegistry.register(agent_id, agent)
        return agent

    return decorator


def build_standard_agent_graph(
    system_prompt: str,
    get_tools_fn: Callable[[], list[BaseTool]],
    parallel_tools: bool = True,
) -> StateGraph:
    """Build a standard ReAct agent graph with llm_call -> tools loop.

    This is the factory function for creating all new agents.
    It eliminates code duplication and ensures consistent behavior.

    All agents use PARALLEL tool execution by default for optimal performance.
    Set parallel_tools=False only for special cases requiring sequential execution
    (e.g., rate-limited APIs, stateful tools, etc.)

    Args:
        system_prompt: The system prompt for this agent
        get_tools_fn: Callable that returns the list of tools
        parallel_tools: If True (default), execute multiple tools in parallel

    Returns:
        StateGraph: The compiled graph ready to be compiled
    """
    # Create reusable nodes
    llm_call = create_llm_call_node(system_prompt, get_tools_fn)
    tool_node = create_tool_node(get_tools_fn, parallel=parallel_tools)

    # Build the graph
    workflow = StateGraph(AgentState)

    # Add nodes
    workflow.add_node("llm_call", llm_call)
    workflow.add_node("tools", tool_node)

    # Add edges
    workflow.add_edge(START, "llm_call")
    workflow.add_conditional_edges("llm_call", should_continue, ["tools", END])
    workflow.add_edge("tools", "llm_call")

    return workflow
