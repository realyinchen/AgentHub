import json
import logging
import time
import uuid
from collections.abc import AsyncGenerator
from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    ToolMessage,
)
from langchain_core.runnables import RunnableConfig
from langgraph.types import Command
from langgraph.graph.state import CompiledStateGraph
from typing import Any

from app.database import adb_manager
from app.schemas.chat import ChatMessage, ToolCall, UserInput
from app.crud import message_step as message_step_crud
from app.crud import chat as chat_crud


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


async def streaming_message_generator(
    user_input: UserInput, agent: CompiledStateGraph
) -> AsyncGenerator[str, None]:
    """
    Generate a stream of messages from the agent using astream_events.

    Uses LangGraph's astream_events (v2) for fine-grained event streaming:
    - on_chat_model_stream: token-by-token streaming
    - on_tool_start: tool call initiation
    - on_tool_end: tool execution result
    - on_chain_end: final message

    Also saves message steps to database for persistence.

    Args:
        user_input: User input containing content, agent_id, thread_id, and thinking_mode
        agent: The compiled state graph agent to use
    """
    kwargs = await handle_input(user_input, agent)
    started_at = time.perf_counter()
    first_chunk_sent = False

    # Track tool calls for mapping tool_call_id to name and args
    pending_tool_calls: dict[str, dict] = {}  # run_id -> {name, args}

    # Track step counter for unique step IDs
    step_counter = 0
    current_llm_step_id: str | None = None

    # Generate session_id for this conversation turn
    session_id = uuid.uuid4()

    # Track accumulated thinking content
    accumulated_thinking = ""

    # Track accumulated content
    accumulated_content = ""

    # Track accumulated token usage for this conversation turn
    accumulated_tokens = {
        "input_tokens": 0,
        "cache_read": 0,
        "output_tokens": 0,
        "reasoning": 0,
        "total_tokens": 0,
    }

    # Send an SSE comment prelude immediately to encourage early flush in proxies.
    yield f": {' ' * 2048}\n\n"

    # Get thread_id from config
    thread_id = kwargs["config"]["configurable"]["thread_id"]
    if isinstance(thread_id, str):
        thread_id = uuid.UUID(thread_id)

    try:
        # Use astream_events for fine-grained streaming
        async for event in agent.astream_events(
            kwargs["input"],
            config=kwargs["config"],
            version="v2",
        ):
            kind = event["event"]
            name = event.get("name", "")
            data = event.get("data", {})
            metadata = event.get("metadata", {})
            node = metadata.get("langgraph_node", "")

            logger.debug(f"Event: kind={kind}, name={name}, node={node}")

            # === LLM Call Start (on_chat_model_start) ===
            # Pre-allocate a new step ID for this LLM call to ensure uniqueness
            if kind == "on_chat_model_start":
                step_counter += 1
                current_llm_step_id = f"step-{step_counter}"

            # === Token Streaming (on_chat_model_stream) ===
            elif kind == "on_chat_model_stream":
                chunk = data.get("chunk")

                # Handle content chunks
                if chunk and hasattr(chunk, "content") and chunk.content:
                    if not first_chunk_sent:
                        first_chunk_sent = True
                        logger.info(
                            "stream first chunk (token) in %.1f ms (agent_id=%s, thread_id=%s)",
                            (time.perf_counter() - started_at) * 1000,
                            user_input.agent_id,
                            user_input.thread_id,
                        )

                    # Handle structured content (DashScope thinking models)
                    if isinstance(chunk.content, list):
                        for block in chunk.content:
                            if isinstance(block, dict):
                                block_type = block.get("type")
                                if block_type == "thinking":
                                    thinking_content = block.get("thinking", "")
                                    if thinking_content:
                                        accumulated_thinking += thinking_content
                                        # Create new LLM step if not exists
                                        if current_llm_step_id is None:
                                            step_counter += 1
                                            current_llm_step_id = f"step-{step_counter}"
                                        yield f"data: {json.dumps({'type': 'llm', 'id': current_llm_step_id, 'step': step_counter, 'content': thinking_content})}\n\n"
                                elif block_type == "text":
                                    text_content = block.get("text", "")
                                    if text_content:
                                        accumulated_content += text_content
                                        yield f"data: {json.dumps({'type': 'token', 'content': text_content})}\n\n"
                    # Handle string content (normal streaming)
                    elif isinstance(chunk.content, str):
                        accumulated_content += chunk.content
                        yield f"data: {json.dumps({'type': 'token', 'content': chunk.content})}\n\n"

                # Handle reasoning_content attribute (DeepSeek-R1 style)
                if (
                    chunk
                    and hasattr(chunk, "reasoning_content")
                    and chunk.reasoning_content
                ):
                    reasoning = chunk.reasoning_content
                    # Create new LLM step if not exists
                    if current_llm_step_id is None:
                        step_counter += 1
                        current_llm_step_id = f"step-{step_counter}"
                    if isinstance(reasoning, str):
                        accumulated_thinking += reasoning
                        yield f"data: {json.dumps({'type': 'llm', 'id': current_llm_step_id, 'step': step_counter, 'content': reasoning})}\n\n"
                    elif isinstance(reasoning, list):
                        reasoning_str = convert_message_content_to_string(reasoning)
                        accumulated_thinking += reasoning_str
                        yield f"data: {json.dumps({'type': 'llm', 'id': current_llm_step_id, 'step': step_counter, 'content': reasoning_str})}\n\n"

            # === Tool Call Start (on_tool_start) ===
            elif kind == "on_tool_start":
                tool_name = name  # The tool name (e.g., "get_current_time")
                tool_args = data.get("args", {})
                run_id = event.get(
                    "run_id", ""
                )  # LangGraph run_id for this tool invocation

                # Store mapping: run_id -> {name, args} for matching with tool_result
                pending_tool_calls[run_id] = {"name": tool_name, "args": tool_args}

                # If there's accumulated thinking, save it as a separate AI thinking step
                # This happens when LLM thinks before deciding to call a tool
                if accumulated_thinking.strip():
                    try:
                        async with adb_manager.session() as session:
                            max_step = (
                                await message_step_crud.get_max_step_number_for_session(
                                    session, thread_id, session_id
                                )
                            )
                            thinking_step_number = max_step + 1
                            await message_step_crud.save_ai_step(
                                db=session,
                                thread_id=thread_id,
                                session_id=session_id,
                                step_number=thinking_step_number,
                                content="",  # No content yet, only thinking
                                thinking=accumulated_thinking,
                            )
                            await session.commit()
                            logger.debug(
                                f"Saved AI thinking step {thinking_step_number} for thread {thread_id}, session {session_id}"
                            )
                    except Exception as e:
                        logger.error(
                            f"Error saving AI thinking step to database: {e}",
                            exc_info=True,
                        )

                    # Clear accumulated thinking for next LLM call
                    accumulated_thinking = ""

                # Also clear accumulated content for next LLM call
                accumulated_content = ""

                # Reset LLM step ID so next LLM call creates a new step
                current_llm_step_id = None

                if not first_chunk_sent:
                    first_chunk_sent = True
                    logger.info(
                        "stream first chunk (tool_call) in %.1f ms (agent_id=%s, thread_id=%s)",
                        (time.perf_counter() - started_at) * 1000,
                        user_input.agent_id,
                        user_input.thread_id,
                    )

                # Increment step counter for tool
                step_counter += 1
                tool_step_id = f"step-{step_counter}"

                # Emit tool_call event with id and step
                yield f"data: {json.dumps({'type': 'tool', 'id': tool_step_id, 'step': step_counter, 'content': {'name': tool_name, 'tool_id': run_id, 'args': tool_args, 'status': 'calling'}})}\n\n"

            # === Tool Call End (on_tool_end) ===
            elif kind == "on_tool_end":
                tool_output = data.get("output", "")
                run_id = event.get("run_id", "")  # Same run_id as in on_tool_start
                tool_info = pending_tool_calls.pop(run_id, {"name": name, "args": {}})
                tool_name = tool_info["name"]
                tool_args = tool_info["args"]

                # Truncate very long outputs for SSE and database
                output_str = str(tool_output)
                if len(output_str) > 2000:
                    output_str = output_str[:2000] + "..."

                # Get current step number from database (for consistent ordering within session)
                try:
                    async with adb_manager.session() as session:
                        max_step = (
                            await message_step_crud.get_max_step_number_for_session(
                                session, thread_id, session_id
                            )
                        )
                        tool_step_number = max_step + 1
                        await message_step_crud.save_tool_step(
                            db=session,
                            thread_id=thread_id,
                            session_id=session_id,
                            step_number=tool_step_number,
                            tool_name=tool_name,
                            tool_args=tool_args,
                            tool_output=output_str,
                        )
                        await session.commit()
                        logger.debug(
                            f"Saved tool step {tool_step_number}: {tool_name} for thread {thread_id}, session {session_id}"
                        )
                except Exception as e:
                    logger.error(
                        f"Error saving tool step to database: {e}", exc_info=True
                    )

                # Emit tool_result event
                yield f"data: {json.dumps({'type': 'tool_result', 'content': {'name': tool_name, 'id': run_id, 'output': output_str}})}\n\n"

            # === LLM Call End (on_chat_model_end) ===
            # This is the most reliable place to capture usage_metadata
            elif kind == "on_chat_model_end":
                output = data.get("output")
                node_name = metadata.get("langgraph_node", "unknown")

                if output and hasattr(output, "usage_metadata"):
                    usage = output.usage_metadata
                    if usage:
                        # Extract token details
                        input_tokens = usage.get("input_tokens", 0)
                        output_tokens = usage.get("output_tokens", 0)
                        total_tokens = usage.get("total_tokens", 0)

                        # Extract cache_read from input_token_details
                        input_token_details = usage.get("input_token_details", {})
                        cache_read = (
                            input_token_details.get("cache_read", 0)
                            if isinstance(input_token_details, dict)
                            else 0
                        )

                        # Extract reasoning from output_token_details
                        output_token_details = usage.get("output_token_details", {})
                        reasoning = (
                            output_token_details.get("reasoning", 0)
                            if isinstance(output_token_details, dict)
                            else 0
                        )

                        # Accumulate tokens
                        accumulated_tokens["input_tokens"] += input_tokens
                        accumulated_tokens["cache_read"] += cache_read
                        accumulated_tokens["output_tokens"] += output_tokens
                        accumulated_tokens["reasoning"] += reasoning
                        accumulated_tokens["total_tokens"] += total_tokens

                        logger.info(
                            f"[{node_name}] Token usage: "
                            f"input={input_tokens}, output={output_tokens}, "
                            f"total={total_tokens}, cache_read={cache_read}, reasoning={reasoning}"
                        )
                        # Emit usage event to frontend
                        yield f"data: {json.dumps({'type': 'usage', 'content': {'node': node_name, 'usage': usage}})}\n\n"
                elif output and hasattr(output, "response_metadata"):
                    # Fallback: try response_metadata for token usage
                    resp_meta = output.response_metadata
                    if "token_usage" in resp_meta:
                        token_usage = resp_meta["token_usage"]
                        input_tokens = token_usage.get("prompt_tokens", 0)
                        output_tokens = token_usage.get("completion_tokens", 0)
                        total_tokens = token_usage.get("total_tokens", 0)

                        # Accumulate tokens (no cache_read or reasoning in fallback)
                        accumulated_tokens["input_tokens"] += input_tokens
                        accumulated_tokens["output_tokens"] += output_tokens
                        accumulated_tokens["total_tokens"] += total_tokens

                        usage = {
                            "input_tokens": input_tokens,
                            "output_tokens": output_tokens,
                            "total_tokens": total_tokens,
                        }
                        logger.info(
                            f"[{node_name}] Token usage (from response_metadata): {usage}"
                        )
                        yield f"data: {json.dumps({'type': 'usage', 'content': {'node': node_name, 'usage': usage}})}\n\n"

            # === Chain End (Final Message) ===
            elif kind == "on_chain_end" and node == "":
                output = data.get("output", {})
                messages = output.get("messages", [])

                if messages:
                    last_message = messages[-1]
                    if hasattr(last_message, "content") and last_message.content:
                        try:
                            chat_message = langchain_to_chat_message(last_message)
                            yield f"data: {json.dumps({'type': 'message', 'content': chat_message.model_dump()})}\n\n"

                            # Save AI response step to database immediately
                            try:
                                async with adb_manager.session() as session:
                                    max_step = await message_step_crud.get_max_step_number_for_session(
                                        session, thread_id, session_id
                                    )
                                    ai_step_number = max_step + 1
                                    await message_step_crud.save_ai_step(
                                        db=session,
                                        thread_id=thread_id,
                                        session_id=session_id,
                                        step_number=ai_step_number,
                                        content=accumulated_content,
                                        thinking=accumulated_thinking
                                        if accumulated_thinking
                                        else None,
                                    )
                                    await session.commit()
                                    logger.debug(
                                        f"Saved AI step {ai_step_number} for thread {thread_id}, session {session_id}"
                                    )
                            except Exception as e:
                                logger.error(
                                    f"Error saving AI step to database: {e}",
                                    exc_info=True,
                                )
                        except Exception as e:
                            logger.error(f"Error parsing final message: {e}")

    except Exception as e:
        logger.error(f"Error in message generator: {e}", exc_info=True)
        yield f"data: {json.dumps({'type': 'error', 'content': str(e)})}\n\n"

    finally:
        # Update conversation token usage in database
        if accumulated_tokens["total_tokens"] > 0:
            try:
                async with adb_manager.session() as session:
                    updated_conv = await chat_crud.update_conversation_tokens(
                        db=session,
                        thread_id=thread_id,
                        input_tokens=accumulated_tokens["input_tokens"],
                        cache_read=accumulated_tokens["cache_read"],
                        output_tokens=accumulated_tokens["output_tokens"],
                        reasoning=accumulated_tokens["reasoning"],
                        total_tokens=accumulated_tokens["total_tokens"],
                    )
                    await session.commit()
                    if updated_conv:
                        logger.info(
                            f"Updated conversation tokens for thread {thread_id}: "
                            f"input={updated_conv.input_tokens}, "
                            f"cache_read={updated_conv.cache_read}, "
                            f"output={updated_conv.output_tokens}, "
                            f"reasoning={updated_conv.reasoning}, "
                            f"total={updated_conv.total_tokens}"
                        )
            except Exception as e:
                logger.error(
                    f"Error updating conversation tokens: {e}",
                    exc_info=True,
                )

        yield "data: [DONE]\n\n"


async def handle_input(
    user_input: UserInput, agent: CompiledStateGraph
) -> dict[str, Any]:
    """
    Parse user input and returns kwargs for agent invocation.

    thinking_mode is passed through config.configurable to the agent's nodes,
    where the LLM is dynamically selected based on this flag.

    model_name is passed through config.configurable to allow dynamic model selection.
    If model_name is provided, it takes precedence over thinking_mode for LLM selection.

    custom_data is stored in HumanMessage.additional_kwargs for persistence,
    and will be restored when loading history.
    """
    thread_id = user_input.thread_id or str(uuid.uuid4())

    configurable = {
        "thread_id": thread_id,
        "thinking_mode": user_input.thinking_mode,  # Pass thinking_mode to agent nodes
        "model_name": user_input.model_name,  # Pass model_name for dynamic model selection
    }

    config = RunnableConfig(configurable=configurable)

    # Create HumanMessage with custom_data in additional_kwargs for persistence
    human_message = HumanMessage(content=user_input.content)
    if user_input.custom_data:
        human_message.additional_kwargs["custom_data"] = user_input.custom_data

    input: Command | dict[str, Any]
    input = {
        "messages": [human_message],
    }

    logger.info(
        "handle_input: thread_id=%s, thinking_mode=%s, model_name=%s, has_custom_data=%s",
        thread_id,
        user_input.thinking_mode,
        user_input.model_name,
        bool(user_input.custom_data),
    )

    kwargs = {
        "input": input,
        "config": config,
    }

    return kwargs
