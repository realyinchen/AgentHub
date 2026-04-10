"""
Reusable LLM streaming module using native litellm.

This module provides a unified interface for streaming LLM calls with:
- Automatic token usage tracking via stream_options
- Support for tools (function calling)
- Support for thinking mode (extra_body)
- Reusable across all agents

Usage:
    from app.core.llm_streaming import streaming_completion

    result = await streaming_completion(
        model="dashscope/qwen-plus",
        messages=[{"role": "user", "content": "Hello"}],
        tools=[...],  # optional
        extra_body={...},  # optional, for thinking mode
    )
    
    print(result.content)  # AI response
    print(result.usage)    # {"prompt_tokens": 10, "completion_tokens": 20, ...}
    print(result.tool_calls)  # list of tool calls if any
"""

import logging
from dataclasses import dataclass, field
from typing import Optional, AsyncGenerator, Any
import json

from litellm import acompletion
from langchain_core.messages import AIMessage

from app.core.model_manager import ModelManager
from app.utils.crypto import decrypt_api_key

logger = logging.getLogger(__name__)


@dataclass
class StreamingResult:
    """
    Result of a streaming LLM completion.
    
    Attributes:
        content: The text content of the response
        tool_calls: List of tool calls (if any)
        usage: Token usage dict with prompt_tokens, completion_tokens, total_tokens, reasoning_tokens
        reasoning: Thinking/reasoning content (if any, for thinking models)
        raw_response: The final AIMessage object for LangGraph compatibility
    """
    content: str = ""
    tool_calls: list = field(default_factory=list)
    usage: dict = field(default_factory=lambda: {
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0,
        "reasoning_tokens": 0
    })
    reasoning: str = ""
    raw_response: Optional[AIMessage] = None


def _convert_messages_to_litellm_format(messages: list) -> list[dict]:
    """
    Convert LangChain messages to litellm format.
    
    Handles:
    - SystemMessage -> {"role": "system", "content": ...}
    - HumanMessage -> {"role": "user", "content": ...}
    - AIMessage -> {"role": "assistant", "content": ..., "tool_calls": ...}
    - ToolMessage -> {"role": "tool", "content": ..., "tool_call_id": ...}
    """
    result = []
    
    for msg in messages:
        msg_type = type(msg).__name__
        
        if msg_type == "SystemMessage":
            result.append({
                "role": "system",
                "content": msg.content
            })
        elif msg_type == "HumanMessage":
            result.append({
                "role": "user",
                "content": msg.content
            })
        elif msg_type == "AIMessage":
            ai_msg: dict[str, Any] = {"role": "assistant"}
            
            # Handle content
            if isinstance(msg.content, str):
                ai_msg["content"] = msg.content
            elif isinstance(msg.content, list):
                # Extract text from structured content
                text_parts = []
                for block in msg.content:
                    if isinstance(block, str):
                        text_parts.append(block)
                    elif isinstance(block, dict) and block.get("type") == "text":
                        text_parts.append(block.get("text", ""))
                ai_msg["content"] = "".join(text_parts)
            else:
                ai_msg["content"] = str(msg.content) if msg.content else ""
            
            # Handle tool calls
            if hasattr(msg, "tool_calls") and msg.tool_calls:
                ai_msg["tool_calls"] = [
                    {
                        "id": tc.get("id", ""),
                        "type": "function",
                        "function": {
                            "name": tc.get("name", ""),
                            "arguments": json.dumps(tc.get("args", {}))
                        }
                    }
                    for tc in msg.tool_calls
                ]
            
            result.append(ai_msg)
        elif msg_type == "ToolMessage":
            result.append({
                "role": "tool",
                "content": str(msg.content),
                "tool_call_id": msg.tool_call_id
            })
        else:
            # Fallback: try to extract role and content
            role = getattr(msg, "type", "user")
            if role == "human":
                role = "user"
            elif role == "ai":
                role = "assistant"
            result.append({
                "role": role,
                "content": str(msg.content) if msg.content else ""
            })
    
    return result


def _convert_tools_to_litellm_format(tools: list) -> list[dict]:
    """
    Convert LangChain tools to litellm/OpenAI format.
    """
    result = []
    
    for tool in tools:
        if hasattr(tool, "name") and hasattr(tool, "description"):
            # LangChain BaseTool
            tool_def = {
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description,
                }
            }
            
            # Get args schema
            if hasattr(tool, "args_schema") and tool.args_schema:
                schema = tool.args_schema.model_json_schema()
                # Remove title from properties
                properties = schema.get("properties", {})
                required = schema.get("required", [])
                tool_def["function"]["parameters"] = {
                    "type": "object",
                    "properties": properties,
                    "required": required
                }
            else:
                tool_def["function"]["parameters"] = {
                    "type": "object",
                    "properties": {}
                }
            
            result.append(tool_def)
        elif isinstance(tool, dict):
            # Already in dict format
            result.append(tool)
    
    return result


async def streaming_completion(
    model: str,
    messages: list,
    tools: list | None = None,
    extra_body: dict | None = None,
    temperature: float = 0,
    **kwargs
) -> StreamingResult:
    """
    Perform a streaming LLM completion with automatic token usage tracking.
    
    This is the recommended way to call LLMs in the application.
    It uses native litellm for maximum compatibility and features.
    
    Args:
        model: Model ID (e.g., "dashscope/qwen-plus", "zai/glm-4")
        messages: List of LangChain messages
        tools: Optional list of LangChain tools
        extra_body: Optional extra body params (e.g., for thinking mode)
        temperature: Temperature for sampling
        **kwargs: Additional arguments passed to litellm.acompletion
    
    Returns:
        StreamingResult with content, tool_calls, usage, and raw_response
    """
    # Get model config from ModelManager
    model_config = ModelManager.get_model(model)
    
    # Get API key
    api_key = None
    if model_config:
        api_key = decrypt_api_key(model_config.api_key) if model_config.api_key else None
    
    # Convert messages to litellm format
    litellm_messages = _convert_messages_to_litellm_format(messages)
    
    # Build kwargs for litellm
    completion_kwargs = {
        "model": model,
        "messages": litellm_messages,
        "stream": True,
        "stream_options": {"include_usage": True},  # Key: enable token usage in streaming
        "temperature": temperature,
    }
    
    # Add API key
    if api_key:
        completion_kwargs["api_key"] = api_key
    
    # Add tools if provided
    if tools:
        completion_kwargs["tools"] = _convert_tools_to_litellm_format(tools)
        completion_kwargs["tool_choice"] = "auto"
    
    # Add extra_body if provided (for thinking mode, etc.)
    if extra_body:
        completion_kwargs["extra_body"] = extra_body
    
    # Add any additional kwargs
    completion_kwargs.update(kwargs)
    
    # Streaming call
    result = StreamingResult()
    content_chunks = []
    tool_calls_chunks = {}  # id -> {name, args_chunks}
    reasoning_chunks = []
    
    try:
        response = await acompletion(**completion_kwargs)
        
        async for chunk in response:  # type: ignore
            # Check for usage in this chunk (typically in the last chunk)
            if hasattr(chunk, "usage") and chunk.usage is not None:
                usage = chunk.usage
                
                # Extract reasoning_tokens from completion_tokens_details
                reasoning_tokens = 0
                if hasattr(usage, "completion_tokens_details") and usage.completion_tokens_details:
                    reasoning_tokens = getattr(usage.completion_tokens_details, "reasoning_tokens", 0) or 0
                
                result.usage = {
                    "prompt_tokens": getattr(usage, "prompt_tokens", 0) or 0,
                    "completion_tokens": getattr(usage, "completion_tokens", 0) or 0,
                    "total_tokens": getattr(usage, "total_tokens", 0) or 0,
                    "reasoning_tokens": reasoning_tokens,
                }
                logger.info(f"Captured token usage: {result.usage}")
            
            # Process choices
            if not chunk.choices:
                continue
            
            delta = chunk.choices[0].delta
            
            if delta is None:
                continue
            
            # Handle content
            if hasattr(delta, "content") and delta.content:
                content_chunks.append(delta.content)
            
            # Handle reasoning (for thinking models)
            if hasattr(delta, "reasoning_content") and delta.reasoning_content:
                reasoning_chunks.append(delta.reasoning_content)
            
            # Handle tool calls
            if hasattr(delta, "tool_calls") and delta.tool_calls:
                for tc in delta.tool_calls:
                    tc_id = tc.id if hasattr(tc, "id") else ""
                    
                    if tc_id:
                        if tc_id not in tool_calls_chunks:
                            tool_calls_chunks[tc_id] = {
                                "id": tc_id,
                                "name": "",
                                "args": ""
                            }
                        if hasattr(tc, "function") and tc.function:
                            if hasattr(tc.function, "name") and tc.function.name:
                                tool_calls_chunks[tc_id]["name"] = tc.function.name
                            if hasattr(tc.function, "arguments") and tc.function.arguments:
                                tool_calls_chunks[tc_id]["args"] += tc.function.arguments
        
        # Combine results
        result.content = "".join(content_chunks)
        result.reasoning = "".join(reasoning_chunks)
        
        # Parse tool calls
        for tc_id, tc_data in tool_calls_chunks.items():
            try:
                args = json.loads(tc_data["args"]) if tc_data["args"] else {}
            except json.JSONDecodeError:
                args = {}
            
            result.tool_calls.append({
                "id": tc_data["id"],
                "name": tc_data["name"],
                "args": args,
                "type": "tool_call"
            })
        
        # Create AIMessage for LangGraph compatibility
        # Include reasoning_content in additional_kwargs for thinking models
        additional_kwargs = {}
        if result.reasoning:
            additional_kwargs["reasoning_content"] = result.reasoning
        
        result.raw_response = AIMessage(
            content=result.content,
            tool_calls=result.tool_calls,
            response_metadata={
                "token_usage": result.usage,
                "usage": result.usage,
            },
            usage_metadata={
                "input_tokens": result.usage["prompt_tokens"],
                "output_tokens": result.usage["completion_tokens"],
                "total_tokens": result.usage["total_tokens"],
                "reasoning_tokens": result.usage["reasoning_tokens"],
            } if result.usage["total_tokens"] > 0 else None,
            additional_kwargs=additional_kwargs if additional_kwargs else None,
        )
        
        logger.info(
            f"Streaming completion done: content_len={len(result.content)}, "
            f"tool_calls={len(result.tool_calls)}, usage={result.usage}"
        )
        
    except Exception as e:
        logger.error(f"Error in streaming completion: {e}")
        raise
    
    return result


async def streaming_completion_with_yield(
    model: str,
    messages: list,
    tools: list | None = None,
    extra_body: dict | None = None,
    temperature: float = 0,
    **kwargs
) -> AsyncGenerator[tuple[str, StreamingResult], None]:
    """
    Streaming completion that yields tokens as they arrive.
    
    Yields:
        tuple of (token_type, data) where:
        - ("token", content) for text tokens
        - ("thinking", content) for reasoning tokens
        - ("tool_call", tool_call_dict) for tool calls
        - ("done", StreamingResult) when complete
    
    Usage:
        async for event_type, data in streaming_completion_with_yield(...):
            if event_type == "token":
                yield f"data: {json.dumps({'type': 'token', 'content': data})}\n\n"
            elif event_type == "done":
                # data is the final StreamingResult
                pass
    """
    # Get model config from ModelManager
    model_config = ModelManager.get_model(model)
    
    # Get API key
    api_key = None
    if model_config:
        api_key = decrypt_api_key(model_config.api_key) if model_config.api_key else None
    
    # Convert messages to litellm format
    litellm_messages = _convert_messages_to_litellm_format(messages)
    
    # Build kwargs for litellm
    completion_kwargs = {
        "model": model,
        "messages": litellm_messages,
        "stream": True,
        "stream_options": {"include_usage": True},
        "temperature": temperature,
    }
    
    if api_key:
        completion_kwargs["api_key"] = api_key
    
    if tools:
        completion_kwargs["tools"] = _convert_tools_to_litellm_format(tools)
        completion_kwargs["tool_choice"] = "auto"
    
    if extra_body:
        completion_kwargs["extra_body"] = extra_body
    
    completion_kwargs.update(kwargs)
    
    result = StreamingResult()
    content_chunks = []
    tool_calls_chunks = {}
    reasoning_chunks = []
    
    try:
        response = await acompletion(**completion_kwargs)
        
        async for chunk in response:  # type: ignore
            # Check for usage
            if hasattr(chunk, "usage") and chunk.usage is not None:
                usage = chunk.usage
                
                # Extract reasoning_tokens from completion_tokens_details
                reasoning_tokens = 0
                if hasattr(usage, "completion_tokens_details") and usage.completion_tokens_details:
                    reasoning_tokens = getattr(usage.completion_tokens_details, "reasoning_tokens", 0) or 0
                
                result.usage = {
                    "prompt_tokens": getattr(usage, "prompt_tokens", 0) or 0,
                    "completion_tokens": getattr(usage, "completion_tokens", 0) or 0,
                    "total_tokens": getattr(usage, "total_tokens", 0) or 0,
                    "reasoning_tokens": reasoning_tokens,
                }
            
            if not chunk.choices:
                continue
            
            delta = chunk.choices[0].delta
            
            if delta is None:
                continue
            
            # Yield content tokens
            if hasattr(delta, "content") and delta.content:
                content_chunks.append(delta.content)
                yield ("token", delta.content)
            
            # Yield reasoning tokens
            if hasattr(delta, "reasoning_content") and delta.reasoning_content:
                reasoning_chunks.append(delta.reasoning_content)
                yield ("thinking", delta.reasoning_content)
            
            # Handle tool calls
            if hasattr(delta, "tool_calls") and delta.tool_calls:
                for tc in delta.tool_calls:
                    tc_id = tc.id if hasattr(tc, "id") else ""
                    
                    if tc_id:
                        if tc_id not in tool_calls_chunks:
                            tool_calls_chunks[tc_id] = {
                                "id": tc_id,
                                "name": "",
                                "args": ""
                            }
                        if hasattr(tc, "function") and tc.function:
                            if hasattr(tc.function, "name") and tc.function.name:
                                tool_calls_chunks[tc_id]["name"] = tc.function.name
                            if hasattr(tc.function, "arguments") and tc.function.arguments:
                                tool_calls_chunks[tc_id]["args"] += tc.function.arguments
        
        # Finalize result
        result.content = "".join(content_chunks)
        result.reasoning = "".join(reasoning_chunks)
        
        for tc_id, tc_data in tool_calls_chunks.items():
            try:
                args = json.loads(tc_data["args"]) if tc_data["args"] else {}
            except json.JSONDecodeError:
                args = {}
            
            result.tool_calls.append({
                "id": tc_data["id"],
                "name": tc_data["name"],
                "args": args,
                "type": "tool_call"
            })
        
        # Create AIMessage
        # Include reasoning_content in additional_kwargs for thinking models
        additional_kwargs = {}
        if result.reasoning:
            additional_kwargs["reasoning_content"] = result.reasoning
        
        result.raw_response = AIMessage(
            content=result.content,
            tool_calls=result.tool_calls,
            response_metadata={
                "token_usage": result.usage,
                "usage": result.usage,
            },
            usage_metadata={
                "input_tokens": result.usage["prompt_tokens"],
                "output_tokens": result.usage["completion_tokens"],
                "total_tokens": result.usage["total_tokens"],
                "reasoning_tokens": result.usage["reasoning_tokens"],
            } if result.usage["total_tokens"] > 0 else None,
            additional_kwargs=additional_kwargs if additional_kwargs else None,
        )
        
        # Yield final result
        yield ("done", result)
        
    except Exception as e:
        logger.error(f"Error in streaming completion with yield: {e}")
        raise