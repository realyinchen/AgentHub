"""Dynamic model selection middleware using LangChain v1's @wrap_model_call.

Enables per-request model switching by reading model_name and thinking_mode
from the runtime context. Uses the LiteLLM Router (via factory.get_llm())
so fallback + retry are automatically handled — no separate fallback
middleware needed.

Follows the official LangChain v1 pattern:
https://docs.langchain.com/oss/python/langchain/agents#dynamic-model

For runtime model switching via context:
https://docs.langchain.com/oss/python/deepagents/models#select-a-model-at-runtime
"""

import logging
from typing import Any, Callable, cast

from langchain.agents.middleware import wrap_model_call, ModelRequest, ModelResponse
from langchain_core.language_models import BaseChatModel

from app.infra.llm import get_llm

logger = logging.getLogger(__name__)


@wrap_model_call
def dynamic_model(
    request: ModelRequest, handler: Callable[[ModelRequest], ModelResponse]
) -> ModelResponse:
    """Dynamically select model based on runtime context.

    Reads model_name and thinking_mode from the runtime context (set by
    ``build_agent_kwargs`` via the ChatbotContext dataclass) and
    overrides the default model if specified.

    This replaces the old pattern of passing model_name via
    RunnableConfig.configurable. Instead, context is passed via
    create_agent's context_schema mechanism.

    Uses the LiteLLM Router (via factory.get_llm()), which provides:
    - Built-in fallback to same-type models on rate-limit/quota errors
    - Automatic retry (2 retries with 1s backoff)
    - No custom fallback middleware needed

    If no model_name is found in context, falls through to the
    default model configured at agent creation time.

    Args:
        request: The model request with runtime context
        handler: The next handler in the middleware chain

    Returns:
        ModelResponse from the selected model
    """
    if request.runtime is None or request.runtime.context is None:
        return handler(request)

    # Extract model config from context
    ctx = request.runtime.context
    model_name = getattr(ctx, "model_name", None)
    if model_name is None and isinstance(ctx, dict):
        model_name = ctx.get("model_name")

    if not model_name:
        return handler(request)

    thinking_mode = getattr(ctx, "thinking_mode", False)
    if thinking_mode is None and isinstance(ctx, dict):
        thinking_mode = ctx.get("thinking_mode", False)

    logger.debug(
        "dynamic_model: switching to model=%s thinking_mode=%s",
        model_name,
        thinking_mode,
    )

    # Create a new LLM instance via the Router (with built-in fallback + retry)
    # ChatLiteLLMRouter is a Runnable, but override() accepts it as a model.
    llm: BaseChatModel = cast(
        Any,
        get_llm(
            model_id=model_name,
            thinking_mode=bool(thinking_mode),
        ),
    )

    return handler(request.override(model=llm))
