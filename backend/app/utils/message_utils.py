import json
import logging
import time
import uuid
from collections.abc import AsyncGenerator
from langchain_core.messages import (
    AIMessageChunk,
    AIMessage,
    BaseMessage,
    HumanMessage,
    ToolMessage,
)
from langchain_core.runnables import RunnableConfig
from langgraph.types import Command
from langgraph.graph.state import CompiledStateGraph
from typing import Any

from app.schemas.chat import ChatMessage, UserInput


def extract_token_counts(message: AIMessage) -> dict[str, int]:
    """
    Extract token counts from an AIMessage's response_metadata or usage_metadata.

    Returns:
        dict with 'input_tokens', 'output_tokens', and 'reasoning_tokens' keys (0 if not found)
    """
    input_tokens = 0
    output_tokens = 0
    reasoning_tokens = 0

    # Try usage_metadata first (LangChain standard)
    if hasattr(message, "usage_metadata") and message.usage_metadata:
        usage = message.usage_metadata
        input_tokens = usage.get("input_tokens", 0) or usage.get("prompt_tokens", 0)
        output_tokens = usage.get("output_tokens", 0) or usage.get(
            "completion_tokens", 0
        )
        # Extract reasoning_tokens from usage_metadata
        reasoning_tokens = usage.get("reasoning_tokens", 0)

    # Fallback to response_metadata (provider-specific)
    if input_tokens == 0 and output_tokens == 0 and message.response_metadata:
        meta = message.response_metadata

        # OpenAI format
        if "token_usage" in meta:
            usage = meta["token_usage"]
            input_tokens = usage.get("prompt_tokens", 0)
            output_tokens = usage.get("completion_tokens", 0)
            # OpenAI o1/R1 models may include reasoning_tokens
            reasoning_tokens = usage.get("reasoning_tokens", 0)

        # Anthropic format
        elif "usage" in meta:
            usage = meta["usage"]
            input_tokens = usage.get("input_tokens", 0)
            output_tokens = usage.get("output_tokens", 0)

        # DashScope/Qwen format
        elif "total_tokens" in meta:
            # DashScope sometimes only provides total, estimate based on typical ratio
            input_tokens = meta.get("input_tokens", 0)
            output_tokens = meta.get("output_tokens", 0)
            # DashScope thinking models may include reasoning_tokens
            reasoning_tokens = meta.get("reasoning_tokens", 0)

    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "reasoning_tokens": reasoning_tokens,
    }


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
                ai_message.tool_calls = message.tool_calls
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


async def streaming_message_generator(
    user_input: UserInput, agent: CompiledStateGraph
) -> AsyncGenerator[str, None]:
    """
    Generate a stream of messages from the agent.

    This is the workhorse method for the /stream endpoint.

    Args:
        user_input: User input containing content, agent_id, thread_id, and thinking_mode
        agent: The compiled state graph agent to use
    """
    kwargs = await handle_input(user_input, agent)
    started_at = time.perf_counter()
    first_chunk_sent = False
    sent_tool_calls: set[str] = set()  # Track sent tool call IDs to avoid duplicates
    # Map tool_call_id to tool name for tool_result events
    tool_call_id_to_name: dict[str, str] = {}
    # Track token usage for this conversation
    total_user_tokens = 0
    total_ai_tokens = 0
    total_reasoning_tokens = 0

    # Send an SSE comment prelude immediately to encourage early flush in proxies.
    yield f": {' ' * 2048}\n\n"
    try:
        # Process streamed events from the graph and yield messages over the SSE stream.
        async for stream_event in agent.astream(
            **kwargs,  # type: ignore
            stream_mode=["updates", "messages"],
        ):
            if not isinstance(stream_event, tuple):
                continue
            stream_mode, event = stream_event
            new_messages = []
            if stream_mode == "updates":
                for node, updates in event.items():
                    # A simple approach to handle agent interrupts.
                    # In a more sophisticated implementation, we could add
                    # some structured ChatMessage type to return the interrupt value.
                    if node == "__interrupt__":
                        continue
                    updates = updates or {}
                    update_messages = updates.get("messages", [])
                    new_messages.extend(update_messages)

            for message in new_messages:
                logger.debug(
                    "Processing message: type=%s, content_preview=%s",
                    type(message).__name__,
                    str(message.content)[:100] if message.content else "",
                )

                # Extract token counts from AI messages
                if isinstance(message, AIMessage):
                    token_counts = extract_token_counts(message)
                    logger.info(
                        "AIMessage token info: input=%d, output=%d, reasoning=%d, has_usage_metadata=%s, has_response_metadata=%s, usage_metadata=%s, response_metadata=%s",
                        token_counts["input_tokens"],
                        token_counts["output_tokens"],
                        token_counts["reasoning_tokens"],
                        hasattr(message, "usage_metadata") and message.usage_metadata is not None,
                        hasattr(message, "response_metadata") and bool(message.response_metadata),
                        message.usage_metadata if hasattr(message, "usage_metadata") else None,
                        message.response_metadata if hasattr(message, "response_metadata") else None,
                    )
                    total_user_tokens += token_counts["input_tokens"]
                    total_ai_tokens += token_counts["output_tokens"]
                    total_reasoning_tokens += token_counts["reasoning_tokens"]

                # Send tool_call event when AI message has tool_calls
                if isinstance(message, AIMessage) and message.tool_calls:
                    logger.info(
                        "AIMessage with tool_calls: %s",
                        [tc.get("name") for tc in message.tool_calls],
                    )
                    for tool_call in message.tool_calls:
                        tool_call_id = tool_call.get("id", "")
                        tool_name = tool_call.get("name", "unknown")
                        tool_args = tool_call.get("args", {})
                        # Store mapping for tool_result
                        if tool_call_id:
                            tool_call_id_to_name[tool_call_id] = tool_name
                        # Avoid sending duplicate tool calls
                        if tool_call_id and tool_call_id not in sent_tool_calls:
                            sent_tool_calls.add(tool_call_id)
                            if not first_chunk_sent:
                                first_chunk_sent = True
                                logger.info(
                                    "stream first chunk (tool_call) in %.1f ms (agent_id=%s, thread_id=%s)",
                                    (time.perf_counter() - started_at) * 1000,
                                    user_input.agent_id,
                                    user_input.thread_id,
                                )
                            yield f"data: {json.dumps({'type': 'tool_call', 'content': {'name': tool_name, 'id': tool_call_id, 'args': tool_args}})}\n\n"

                # Send tool_result event when ToolMessage is received
                if isinstance(message, ToolMessage):
                    tool_call_id = message.tool_call_id
                    tool_name = tool_call_id_to_name.get(tool_call_id, "unknown")
                    tool_output = convert_message_content_to_string(message.content)
                    # Truncate very long outputs for SSE
                    if len(tool_output) > 2000:
                        tool_output = tool_output[:2000] + "..."
                    yield f"data: {json.dumps({'type': 'tool_result', 'content': {'name': tool_name, 'id': tool_call_id, 'output': tool_output}})}\n\n"

                try:
                    chat_message = langchain_to_chat_message(message)
                except Exception as e:
                    logger.error(f"Error parsing message: {e}")
                    yield f"data: {json.dumps({'type': 'error', 'content': 'Unexpected error'})}\n\n"
                    continue
                # LangGraph re-sends the input message, which feels weird, so drop it
                if (
                    chat_message.type == "human"
                    and chat_message.content == user_input.content
                ):
                    continue
                # Skip tool messages in the main message stream (we already sent tool_result)
                if chat_message.type == "tool":
                    continue
                if not first_chunk_sent:
                    first_chunk_sent = True
                    logger.info(
                        "stream first chunk in %.1f ms (agent_id=%s, thread_id=%s)",
                        (time.perf_counter() - started_at) * 1000,
                        user_input.agent_id,
                        user_input.thread_id,
                    )
                yield f"data: {json.dumps({'type': 'message', 'content': chat_message.model_dump()})}\n\n"

            if stream_mode == "messages":
                msg, _ = event
                # non-LLM nodes will send extra messages, like ToolMessage, we need to drop them.
                if not isinstance(msg, AIMessageChunk):
                    continue

                # Handle thinking content from DashScope thinking models
                # The content can be structured as list[dict] with 'type' field
                # e.g., [{'type': 'thinking', 'thinking': '...'}, {'type': 'text', 'text': '...'}]
                if isinstance(msg.content, list):
                    for block in msg.content:
                        if isinstance(block, dict):
                            block_type = block.get("type")

                            # Handle thinking block
                            if block_type == "thinking":
                                thinking_content = block.get("thinking", "")
                                if thinking_content:
                                    if not first_chunk_sent:
                                        first_chunk_sent = True
                                        logger.info(
                                            "stream first chunk (thinking) in %.1f ms",
                                            (time.perf_counter() - started_at) * 1000,
                                        )
                                    yield f"data: {json.dumps({'type': 'thinking', 'content': thinking_content})}\n\n"

                            # Handle text block (final answer)
                            elif block_type == "text":
                                text_content = block.get("text", "")
                                if text_content:
                                    if not first_chunk_sent:
                                        first_chunk_sent = True
                                        logger.info(
                                            "stream first chunk in %.1f ms",
                                            (time.perf_counter() - started_at) * 1000,
                                        )
                                    yield f"data: {json.dumps({'type': 'token', 'content': text_content})}\n\n"

                # Handle reasoning_content attribute (DeepSeek-R1 style)
                reasoning_content = getattr(msg, "reasoning_content", None)
                if reasoning_content:
                    if not first_chunk_sent:
                        first_chunk_sent = True
                        logger.info(
                            "stream first chunk (thinking) in %.1f ms (agent_id=%s, thread_id=%s)",
                            (time.perf_counter() - started_at) * 1000,
                            user_input.agent_id,
                            user_input.thread_id,
                        )
                    yield f"data: {json.dumps({'type': 'thinking', 'content': convert_message_content_to_string(reasoning_content)})}\n\n"

                # Handle string content (normal streaming)
                content = msg.content
                if content and isinstance(content, str):
                    # Empty content in the context of OpenAI usually means
                    # that the model is asking for a tool to be invoked.
                    # So we only print non-empty content.
                    if not first_chunk_sent:
                        first_chunk_sent = True
                        logger.info(
                            "stream first chunk in %.1f ms (agent_id=%s, thread_id=%s)",
                            (time.perf_counter() - started_at) * 1000,
                            user_input.agent_id,
                            user_input.thread_id,
                        )
                    yield f"data: {json.dumps({'type': 'token', 'content': content})}\n\n"
    except Exception as e:
        logger.error(f"Error in message generator: {e}")
        yield f"data: {json.dumps({'type': 'error', 'content': 'Internal server error'})}\n\n"
    finally:
        # Update token counts in database if we tracked any tokens
        if total_user_tokens > 0 or total_ai_tokens > 0 or total_reasoning_tokens > 0:
            try:
                from app.database import adb_manager
                from app.crud.chat import update_conversation_tokens
                from uuid import UUID

                thread_id = (
                    kwargs.get("config", {}).get("configurable", {}).get("thread_id")
                )
                if thread_id:
                    # Convert thread_id to UUID if it's a string
                    if isinstance(thread_id, str):
                        thread_id = UUID(thread_id)
                    elif not isinstance(thread_id, UUID):
                        thread_id = UUID(str(thread_id))
                    async with adb_manager.session() as session:
                        await update_conversation_tokens(
                            db=session,
                            thread_id=thread_id,
                            user_tokens=total_user_tokens,
                            ai_tokens=total_ai_tokens,
                            reasoning_tokens=total_reasoning_tokens,
                        )
                    logger.info(
                        "Updated token counts: thread_id=%s, user_tokens=%d, ai_tokens=%d, reasoning_tokens=%d",
                        thread_id,
                        total_user_tokens,
                        total_ai_tokens,
                        total_reasoning_tokens,
                    )
            except Exception as e:
                logger.error(f"Failed to update token counts: {e}")
        else:
            # Fallback: Use litellm token_counter to estimate tokens if provider didn't return usage
            try:
                import litellm
                
                # Count tokens from the conversation messages
                # This is an estimate, not exact provider usage
                user_content = user_input.content
                estimated_input_tokens = litellm.token_counter(
                    text=user_content,
                    model=user_input.model_name or "gpt-3.5-turbo"
                )
                
                # We don't have the full AI response here, so we can't count output tokens
                # Log a warning that we're using estimated tokens
                logger.warning(
                    "Provider did not return token usage. Estimated input tokens: %d (model=%s)",
                    estimated_input_tokens,
                    user_input.model_name,
                )
            except Exception as e:
                logger.warning("Failed to estimate tokens: %s", e)
        
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
