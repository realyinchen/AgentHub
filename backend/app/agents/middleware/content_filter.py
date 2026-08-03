"""Content filter middleware — removes non-standard content types before model call.

DashScope only support specific content types: 'text', 'image_url', 'video_url', 'video'

When thinking/reasoning mode is enabled, AI responses may contain content blocks
with types like 'thinking', 'reasoning', or 'non_standard' that are rejected
by these providers on subsequent turns.

This middleware filters message content to only include supported types,
preventing BadRequestError on multi-turn conversations.

Usage::

    from app.agents.middleware.content_filter import content_filter

    # In create_agent:
    agent = create_agent(
        middleware=[..., content_filter],
    )
"""

import logging
from typing import Any, Callable

from langchain.agents.middleware import AgentMiddleware, ModelRequest, ModelResponse
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage

from app.infra.llm.history import model_history_projector

logger = logging.getLogger(__name__)

# Content types supported by most LLM providers (OpenAI-compatible)
# DashScope: text, image_url, video_url, video
# ZhipuAI: text, image_url
# OpenAI: text, image_url
SUPPORTED_CONTENT_TYPES: set[str] = {"text", "image_url", "video_url", "video"}


class ContentFilterMiddleware(AgentMiddleware):
    """Filter non-standard content types from messages before model call.

    Iterates through all messages in the input and:
    1. Delegates assistant history to the shared model-history projector
    2. Keeps other string content as-is
    3. Filters other list content to only include supported types
    4. Logs warnings when filtering removes content

    This ensures compatibility with providers that reject unknown content types.
    """

    def _filter_message_content(self, msg: BaseMessage) -> BaseMessage:
        """Filter content blocks to only supported types.

        Args:
            msg: A LangChain message (HumanMessage, AIMessage, ToolMessage)

        Returns:
            A new message instance with filtered content
        """
        if isinstance(msg, AIMessage):
            return model_history_projector.project_message(msg)

        # String content - no filtering needed
        if isinstance(msg.content, str):
            return msg

        # List content - filter to supported types
        if isinstance(msg.content, list):
            filtered_content: list[Any] = []
            for block in msg.content:
                # Keep string blocks - convert to dict format
                if isinstance(block, str):
                    filtered_content.append({"type": "text", "text": block})
                    continue

                # Keep dict blocks with supported types
                if isinstance(block, dict):
                    block_type = block.get("type", "")
                    if block_type in SUPPORTED_CONTENT_TYPES:
                        filtered_content.append(block)
                    elif block_type == "thinking":
                        # Log thinking content being filtered
                        logger.debug(
                            "Filtering 'thinking' content block from %s (len=%d)",
                            type(msg).__name__,
                            len(str(block.get("thinking", ""))),
                        )
                    elif block_type == "reasoning":
                        # Log reasoning content being filtered
                        logger.debug(
                            "Filtering 'reasoning' content block from %s (len=%d)",
                            type(msg).__name__,
                            len(str(block.get("reasoning", ""))),
                        )
                    elif block_type and block_type not in SUPPORTED_CONTENT_TYPES:
                        # Log unknown non-standard types
                        logger.warning(
                            "Filtering unknown content type '%s' from %s",
                            block_type,
                            type(msg).__name__,
                        )

            # If all content was filtered out, create a placeholder
            if not filtered_content:
                logger.warning(
                    "All content filtered from %s, using empty text placeholder",
                    type(msg).__name__,
                )
                filtered_content = [{"type": "text", "text": "..."}]

            # Create new message with filtered content
            # We need to preserve all other attributes
            if isinstance(msg, HumanMessage):
                return HumanMessage(
                    content=filtered_content,  # type: ignore[arg-type]
                    additional_kwargs=msg.additional_kwargs,
                )
            elif isinstance(msg, ToolMessage):
                return ToolMessage(
                    content=filtered_content,  # type: ignore[arg-type]
                    tool_call_id=msg.tool_call_id,
                    name=msg.name,
                    additional_kwargs=msg.additional_kwargs,
                )
            else:
                # Generic BaseMessage - shouldn't happen but handle gracefully
                return msg.__class__(content=filtered_content)  # type: ignore[call-arg]

        # Unknown content type - return as-is with warning
        logger.warning(
            "Unknown content type %s in %s, passing through",
            type(msg.content).__name__,
            type(msg).__name__,
        )
        return msg

    def wrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], ModelResponse],
    ) -> ModelResponse:
        """Sync version: filter content before model call."""
        # ModelRequest.messages is the list of messages
        messages = getattr(request, "messages", [])
        filtered_messages = [self._filter_message_content(msg) for msg in messages]
        # Use override to replace messages
        return handler(request.override(messages=filtered_messages))  # type: ignore[misc]

    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], ModelResponse],
    ) -> ModelResponse:
        """Async version: filter content before model call."""
        # ModelRequest.messages is the list of messages
        messages = getattr(request, "messages", [])
        filtered_messages = [self._filter_message_content(msg) for msg in messages]
        # Use override to replace messages
        return await handler(request.override(messages=filtered_messages))  # type: ignore[misc]


# Module-level singleton for convenience
content_filter = ContentFilterMiddleware()
