import json
import logging
import time
import uuid
from collections.abc import AsyncGenerator, Sequence
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

from app.database import get_database
from app.schemas.chat import ChatMessage, ToolCall, UserInput
from app.core.errors import format_sse_error
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


async def save_messages_to_steps(
    thread_id: uuid.UUID,
    session_id: uuid.UUID,
    messages: list[BaseMessage],
    user_input_content: str | None = None,
    model_name: str | None = None,
) -> None:
    """
    Save messages from output.messages to message_steps table.

    Since on_chain_end output.messages contains ALL messages (including history),
    we use user_input_content to find the start of the current turn's messages.
    Only messages from the current turn are saved.

    Args:
        thread_id: The thread/conversation ID
        session_id: The session ID for this turn
        messages: Full message list from on_chain_end output
        user_input_content: The user's input content to find current turn start
        model_name: The model name used for AI messages
    """
    # Find the start index of current turn's messages
    start_index = 0
    if user_input_content:
        # Find the LAST occurrence of a HumanMessage with matching content
        # This identifies the current turn's input in the full message list
        for i in range(len(messages) - 1, -1, -1):
            msg = messages[i]
            if isinstance(msg, HumanMessage):
                content = convert_message_content_to_string(msg.content)
                if content == user_input_content:
                    start_index = i
                    break

    # Only process messages from the current turn
    current_turn_messages = messages[start_index:]
    logger.debug(
        f"[SAVE] Current turn: {len(current_turn_messages)} messages "
        f"(starting from index {start_index} of {len(messages)} total)"
    )

    step_number = 0
    # Map tool_call_id to tool name for ToolMessages
    tool_call_id_to_name: dict[str, str] = {}
    # Map tool_call_id to tool args for ToolMessages
    tool_call_id_to_args: dict[str, dict] = {}

    db = get_database()
    async with db.session() as session:
        for msg in current_turn_messages:
            if isinstance(msg, HumanMessage):
                step_number += 1
                content = convert_message_content_to_string(msg.content)
                await message_step_crud.save_human_step(
                    db=session,
                    thread_id=thread_id,
                    session_id=session_id,
                    step_number=step_number,
                    content=content,
                )
                logger.debug(
                    f"[SAVE] Human step {step_number}: {content[:50]}..."
                )

            elif isinstance(msg, AIMessage):
                content = convert_message_content_to_string(msg.content)
                thinking = _extract_thinking_content(msg)

                # Store tool_calls mapping for subsequent ToolMessages
                # (always do this, even if we don't save the AI step)
                if msg.tool_calls:
                    for tc in msg.tool_calls:
                        tool_call_id = tc.get("id", "")
                        if tool_call_id:
                            tool_call_id_to_name[tool_call_id] = tc.get("name", "")
                            tool_call_id_to_args[tool_call_id] = tc.get("args", {})

                # Only save AI step if it has content or thinking
                # Skip AI messages that only have tool_calls (no content/thinking)
                has_content = bool(content.strip())
                has_thinking = bool(thinking.strip())

                if has_content or has_thinking:
                    step_number += 1

                    # Convert tool_calls to list format for database
                    tool_calls_list = None
                    if msg.tool_calls:
                        tool_calls_list = [
                            {
                                "name": tc.get("name", ""),
                                "id": tc.get("id", ""),
                                "args": tc.get("args", {}),
                            }
                            for tc in msg.tool_calls
                        ]

                    await message_step_crud.save_ai_step(
                        db=session,
                        thread_id=thread_id,
                        session_id=session_id,
                        step_number=step_number,
                        content=content if content else None,
                        thinking=thinking if thinking else None,
                        tool_calls=tool_calls_list,
                        model_name=model_name,
                    )
                    logger.debug(
                        f"[SAVE] AI step {step_number}: "
                        f"content_len={len(content)}, "
                        f"thinking_len={len(thinking) if thinking else 0}, "
                        f"tool_calls={len(tool_calls_list) if tool_calls_list else 0}"
                    )
                else:
                    # Skip saving this AI message (only has tool_calls, no content/thinking)
                    logger.debug(
                        f"[SAVE] Skipping AI message (no content/thinking, only tool_calls: {len(msg.tool_calls) if msg.tool_calls else 0})"
                    )

            elif isinstance(msg, ToolMessage):
                step_number += 1
                # Get tool name from mapping (by tool_call_id)
                tool_call_id = msg.tool_call_id
                tool_name = tool_call_id_to_name.get(tool_call_id, "")
                tool_args = tool_call_id_to_args.get(tool_call_id, {})

                # Get complete output (no truncation)
                tool_output = convert_message_content_to_string(msg.content)

                await message_step_crud.save_tool_step(
                    db=session,
                    thread_id=thread_id,
                    session_id=session_id,
                    step_number=step_number,
                    tool_name=tool_name,
                    tool_args=tool_args,
                    tool_output=tool_output,
                    tool_call_id=tool_call_id,
                )
                logger.debug(
                    f"[SAVE] Tool step {step_number}: "
                    f"name={tool_name}, "
                    f"tool_call_id={tool_call_id}, "
                    f"output_len={len(tool_output)}"
                )

        await session.commit()
        logger.info(
            f"[SAVE] Completed saving {step_number} steps for "
            f"thread={thread_id}, session={session_id}"
        )


async def streaming_message_generator(
    user_input: UserInput, agent: CompiledStateGraph
) -> AsyncGenerator[str, None]:
    """
    Generate a stream of messages from the agent using astream_events.

    Uses LangGraph's astream_events (v2) for fine-grained event streaming:
    - on_chat_model_stream: token-by-token streaming (for final response only)
    - on_tool_start: emit step status event (tool calling)
    - on_chain_end: final message and complete persistence

    SSE events are simplified to only show step status.
    Complete data is saved to database in on_chain_end.

    Args:
        user_input: User input containing content, agent_id, thread_id, and thinking_mode
        agent: The compiled state graph agent to use
    """
    kwargs = await handle_input(user_input, agent)
    started_at = time.perf_counter()
    first_chunk_sent = False

    # Track step counter for SSE events (just for display)
    step_counter = 0

    # Generate session_id for this conversation turn
    session_id = uuid.uuid4()

    # Track accumulated content for final response streaming
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
            if kind == "on_chat_model_start":
                run_id = event.get("run_id", "")

                # Emit human step on first LLM call
                if step_counter == 0:
                    step_counter += 1
                    yield f"data: {json.dumps({'type': 'step', 'step': step_counter, 'action': 'human', 'content': user_input.content})}\n\n"
                    first_chunk_sent = True
                    logger.debug(f"[SSE] Step {step_counter}: human")

                # Note: ai_thinking step is deferred to on_chat_model_end
                # where we can check if the AI has actual content

            # === Token Streaming (on_chat_model_stream) ===
            # Only stream tokens for final response display
            elif kind == "on_chat_model_stream":
                chunk = data.get("chunk")

                # Handle content chunks
                if chunk and hasattr(chunk, "content") and chunk.content:
                    if not first_chunk_sent:
                        first_chunk_sent = True
                        logger.info(
                            "stream first chunk (token) in %.1f ms",
                            (time.perf_counter() - started_at) * 1000,
                        )

                    # Handle structured content (DashScope thinking models)
                    if isinstance(chunk.content, list):
                        for block in chunk.content:
                            if isinstance(block, dict):
                                block_type = block.get("type")
                                if block_type == "text":
                                    text_content = block.get("text", "")
                                    if text_content:
                                        accumulated_content += text_content
                                        # Only stream text tokens for final response
                                        yield f"data: {json.dumps({'type': 'token', 'content': text_content})}\n\n"
                    # Handle string content (normal streaming)
                    elif isinstance(chunk.content, str):
                        accumulated_content += chunk.content
                        yield f"data: {json.dumps({'type': 'token', 'content': chunk.content})}\n\n"

            # === Tool Call Start (on_tool_start) ===
            elif kind == "on_tool_start":
                tool_name = name

                if not first_chunk_sent:
                    first_chunk_sent = True
                    logger.info(
                        "stream first chunk (tool_call) in %.1f ms",
                        (time.perf_counter() - started_at) * 1000,
                    )

                # Emit tool_call step status
                step_counter += 1
                yield f"data: {json.dumps({'type': 'step', 'step': step_counter, 'action': 'tool_call', 'name': tool_name, 'status': 'calling'})}\n\n"
                logger.debug(f"[SSE] Step {step_counter}: tool_call, name={tool_name}")

            # === Tool Call End (on_tool_end) ===
            elif kind == "on_tool_end":
                # Emit tool_result step status (just indicate completion)
                yield f"data: {json.dumps({'type': 'step', 'step': step_counter, 'action': 'tool_result', 'status': 'completed'})}\n\n"
                logger.debug(f"[SSE] Step {step_counter}: tool_result completed")

            # === LLM Call End (on_chat_model_end) ===
            elif kind == "on_chat_model_end":
                output = data.get("output")
                node_name = metadata.get("langgraph_node", "unknown")

                # Capture token usage
                if output and hasattr(output, "usage_metadata"):
                    usage = output.usage_metadata
                    if usage:
                        input_tokens = usage.get("input_tokens", 0)
                        output_tokens = usage.get("output_tokens", 0)
                        total_tokens = usage.get("total_tokens", 0)

                        input_token_details = usage.get("input_token_details", {})
                        cache_read = (
                            input_token_details.get("cache_read", 0)
                            if isinstance(input_token_details, dict)
                            else 0
                        )

                        output_token_details = usage.get("output_token_details", {})
                        reasoning = (
                            output_token_details.get("reasoning", 0)
                            if isinstance(output_token_details, dict)
                            else 0
                        )

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
                        yield f"data: {json.dumps({'type': 'usage', 'content': {'node': node_name, 'usage': usage}})}\n\n"

                elif output and hasattr(output, "response_metadata"):
                    resp_meta = output.response_metadata
                    if "token_usage" in resp_meta:
                        token_usage = resp_meta["token_usage"]
                        input_tokens = token_usage.get("prompt_tokens", 0)
                        output_tokens = token_usage.get("completion_tokens", 0)
                        total_tokens = token_usage.get("total_tokens", 0)

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

                # Emit ai_thinking step only if AI has actual text content
                # (skip if AI only has tool_calls with no content)
                has_content = False
                if output:
                    content = getattr(output, "content", "")
                    if isinstance(content, str) and content.strip():
                        has_content = True
                    elif isinstance(content, list):
                        # Check for text blocks in structured content
                        for block in content:
                            if isinstance(block, dict) and block.get("type") == "text":
                                if block.get("text", "").strip():
                                    has_content = True
                                    break

                if has_content:
                    step_counter += 1
                    yield f"data: {json.dumps({'type': 'step', 'step': step_counter, 'action': 'ai_thinking', 'status': 'thinking...'})}\n\n"
                    logger.debug(f"[SSE] Step {step_counter}: ai_thinking (has content)")

                if output and hasattr(output, "tool_calls") and output.tool_calls:
                    logger.debug(f"[SSE] AI has tool_calls: {len(output.tool_calls)}")

            # === Chain End (Final Message) ===
            elif kind == "on_chain_end" and node == "":
                output = data.get("output", {})
                messages = output.get("messages", [])
                run_id = event.get("run_id", "")

                logger.debug(
                    f"[TRACE] on_chain_end: run_id={run_id}, messages_count={len(messages)}"
                )

                if messages:
                    last_message = messages[-1]
                    if hasattr(last_message, "content") and last_message.content:
                        try:
                            chat_message = langchain_to_chat_message(last_message)

                            # Emit final message event
                            yield f"data: {json.dumps({'type': 'message', 'content': chat_message.model_dump()})}\n\n"

                            # Save current turn's messages to database with complete data
                            try:
                                await save_messages_to_steps(
                                    thread_id=thread_id,
                                    session_id=session_id,
                                    messages=messages,
                                    user_input_content=user_input.content,
                                    model_name=user_input.model_name,
                                )
                            except Exception as e:
                                logger.error(
                                    f"[TRACE] Failed to save messages to steps: {e}",
                                    exc_info=True,
                                )
                        except Exception as e:
                            logger.error(f"Error parsing final message: {e}")

    except Exception as e:
        # Use format_sse_error to ensure user-friendly messages are returned
        error_data = format_sse_error(e)
        yield f"data: {json.dumps(error_data)}\n\n"

    finally:
        # Update conversation token usage in database
        if accumulated_tokens["total_tokens"] > 0:
            try:
                db = get_database()
                async with db.session() as session:
                    updated_conv = await chat_crud.update_conversation_tokens(
                        db=session,
                        thread_id=thread_id,
                        input_tokens=accumulated_tokens["input_tokens"],
                        cache_read=accumulated_tokens["cache_read"],
                        output_tokens=accumulated_tokens["output_tokens"],
                        reasoning=accumulated_tokens["reasoning"],
                        total_tokens=accumulated_tokens["total_tokens"],
                    )
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