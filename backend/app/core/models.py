# pyright: reportArgumentType=false

import logging
from langchain_core.messages import AIMessage

from app.core.model_manager import ModelManager


logger = logging.getLogger(__name__)


async def aembedding_model() -> str:
    """
    Get the embedding model ID (async).

    Returns:
        Model ID string for embedding
    """
    return await ModelManager.get_embedding_model()


def embedding_model() -> str:
    """
    Get the embedding model ID (sync wrapper for backward compatibility).

    WARNING: This function creates a new event loop if called from sync context.
    Prefer using aembedding_model() in async code.

    Returns:
        Model ID string for embedding
    """
    import asyncio

    try:
        _ = asyncio.get_running_loop()
        # We're in an async context, but this is a sync function
        # This is a code smell - caller should use aembedding_model()
        logger.warning(
            "embedding_model() called from async context. "
            "Consider using aembedding_model() for better performance."
        )
        import concurrent.futures

        with concurrent.futures.ThreadPoolExecutor() as executor:
            future = executor.submit(asyncio.run, ModelManager.get_embedding_model())
            return future.result()
    except RuntimeError:
        return asyncio.run(ModelManager.get_embedding_model())


async def aget_llm(thinking_mode: bool = False, model_id: str | None = None):
    """
    Get the appropriate LLM based on thinking_mode or model_id (async).

    This is the preferred method for getting LLM instances in async code.

    Args:
        thinking_mode: If True, return the thinking model; otherwise return the normal model.
        model_id: If provided, return the LLM for this specific model ID (takes precedence).

    Returns:
        ChatLiteLLMRouter instance

    Raises:
        ValueError: If no models are configured
    """
    return await ModelManager.get_llm(model_id=model_id, thinking_mode=thinking_mode)


def get_llm(thinking_mode: bool = False, model_name: str | None = None):
    """
    Get the appropriate LLM based on thinking_mode or model_name (sync wrapper).

    WARNING: This function creates a new event loop if called from sync context.
    Prefer using aget_llm() in async code for better performance.

    Args:
        thinking_mode: If True, return the thinking model; otherwise return the normal model.
        model_name: If provided, return the LLM for this specific model name (takes precedence).

    Returns:
        ChatLiteLLMRouter instance

    Raises:
        ValueError: If no models are configured
    """
    import asyncio

    try:
        _ = asyncio.get_running_loop()
        # We're in an async context, but this is a sync function
        # This is a code smell - caller should use aget_llm()
        logger.warning(
            "get_llm() called from async context. "
            "Consider using aget_llm() for better performance."
        )
        import concurrent.futures

        with concurrent.futures.ThreadPoolExecutor() as executor:
            future = executor.submit(
                asyncio.run,
                ModelManager.get_llm(model_id=model_name, thinking_mode=thinking_mode),
            )
            return future.result()
    except RuntimeError:
        # No running event loop, run directly
        return asyncio.run(
            ModelManager.get_llm(model_id=model_name, thinking_mode=thinking_mode)
        )


def is_thinking_mode_available(model_id: str | None = None) -> bool:
    """
    Check if thinking mode is available for a specific model.

    Args:
        model_id: Model ID to check. If None, checks the default LLM.

    Returns:
        True if the model supports thinking mode
    """
    if model_id is None:
        # Check default LLM
        default_id = ModelManager.get_default_llm_id()
        if default_id is None:
            return False
        return ModelManager.is_thinking_mode_available(default_id)
    return ModelManager.is_thinking_mode_available(model_id)


def extract_thinking_and_answer(msg: AIMessage) -> dict:
    """
    Extract thinking content and final answer from AIMessage.

    Handles both structured content (list of blocks) and string content.

    Args:
        msg: AIMessage from LLM response

    Returns:
        dict with 'thinking' and 'final_answer' keys
    """
    thinking = ""
    final_answer = ""

    if isinstance(msg.content, list):
        # Structured content: [{"type": "thinking", "thinking": "..."}, {"type": "text", "text": "..."}]
        for block in msg.content:
            if isinstance(block, dict):
                block_type = block.get("type")
                if block_type == "thinking":
                    thinking += block.get("thinking", "") + "\n"
                elif block_type == "text":
                    final_answer += block.get("text", "") + "\n"
    elif isinstance(msg.content, str):
        # Fallback to string content
        final_answer = msg.content

    # Alternative: get reasoning from additional_kwargs
    reasoning_from_kwargs = msg.additional_kwargs.get("reasoning_content", "")
    if not thinking.strip() and reasoning_from_kwargs:
        thinking = reasoning_from_kwargs.strip()

    return {
        "thinking": thinking.strip(),
        "final_answer": final_answer.strip(),
    }
