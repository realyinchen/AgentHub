"""Dynamic model selection middleware using LangChain v1's AgentMiddleware.

Enables per-request model switching by reading model_name and thinking_mode
from the runtime context. Uses the LiteLLM Router (via factory.get_llm())
so fallback + retry are automatically handled — no separate fallback
middleware needed.

Follows the official LangChain v1 pattern for async middleware:
https://docs.langchain.com/oss/python/langchain/middleware/custom#class-based-middleware

For runtime model switching via context:
https://docs.langchain.com/oss/python/deepagents/models#select-a-model-at-runtime
"""

import logging
from typing import Callable, cast

from langchain.agents.middleware import AgentMiddleware, ModelRequest, ModelResponse
from langchain_core.messages import AIMessage
from langchain_core.language_models.chat_models import BaseChatModel

# Lazy import to avoid circular dependency:
# infra.llm.manager → utils.crypto → utils → utils.streaming → utils.request_handler →
# agents.context → agents → agents.supervisor → agents.middleware.model → infra.llm.manager
logger = logging.getLogger(__name__)


class DynamicModelMiddleware(AgentMiddleware):
    """Dynamically select model based on runtime context.

    Reads ``model_name`` and ``thinking_mode`` from the runtime context (set by
    ``build_agent_kwargs`` via a ``@dataclass`` context, e.g. ``AgentRuntimeContext``)
    and overrides the default model if specified.

    Per the LangChain v1 official pattern, all agents in this project MUST use
    a ``@dataclass`` for ``context_schema`` — attribute access (``ctx.model_name``)
    is the only supported form. Dict / TypedDict contexts are not supported.

    Uses the LiteLLM Router (via ``factory.get_llm()``), which provides:
    - Built-in fallback to same-type models on rate-limit/quota errors
    - Automatic retry (2 retries with 1s backoff)
    - No custom fallback middleware needed

    If no ``model_name`` is found in context, falls through to the default
    model configured at agent creation time.

    This class implements both sync (wrap_model_call) and async (awrap_model_call)
    methods to support both invocation contexts, following the official LangChain
    middleware pattern.

    See: https://docs.langchain.com/oss/python/langchain/middleware/custom#class-based-middleware
    """

    def _get_model_override(self, request: ModelRequest) -> BaseChatModel | None:
        """Extract model from context and create new LLM instance.

        Returns None if no override is needed.
        """
        if request.runtime is None or request.runtime.context is None:
            return None

        # Extract model config from the dataclass context (attribute access only).
        ctx = request.runtime.context
        model_name = getattr(ctx, "model_name", None)
        if not model_name:
            return None

        thinking_mode = bool(getattr(ctx, "thinking_mode", False))

        # Lazy import to avoid circular dependency at module load time.
        from app.infra.llm import get_llm

        # Create a new LLM instance via the Router (with built-in fallback + retry).
        # ChatLiteLLMRouter is a Runnable; override() accepts it as a model.
        return cast(
            BaseChatModel,
            get_llm(
                model_id=model_name,
                thinking_mode=thinking_mode,
            ),
        )

    def _preserve_reasoning(self, response: ModelResponse) -> ModelResponse:
        """Normalize provider reasoning onto AIMessage.additional_kwargs."""
        from app.utils.message import extract_thinking

        for message in response.result:
            if not isinstance(message, AIMessage):
                continue
            thinking = extract_thinking(message)
            if not thinking:
                continue
            message.additional_kwargs.setdefault("reasoning_content", thinking)
            message.additional_kwargs.setdefault("thinking", thinking)
        return response

    def wrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], ModelResponse],
    ) -> ModelResponse:
        """Sync version: dynamically select model based on runtime context."""
        model = self._get_model_override(request)
        if model is None:
            return self._preserve_reasoning(handler(request))
        return self._preserve_reasoning(handler(request.override(model=model)))

    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], ModelResponse],
    ) -> ModelResponse:
        """Async version: dynamically select model based on runtime context.

        Called when the agent is invoked in an async context (e.g., astream(), ainvoke()).
        Note: The handler returns a coroutine in async context despite type hint showing ModelResponse.
        """
        model = self._get_model_override(request)
        if model is None:
            response = await handler(request)  # type: ignore[misc]
        else:
            response = await handler(request.override(model=model))  # type: ignore[misc]
        return self._preserve_reasoning(response)


# Module-level singleton instance for convenience
dynamic_model = DynamicModelMiddleware()
