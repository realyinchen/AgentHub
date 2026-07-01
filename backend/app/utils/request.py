"""Request → Agent parameter orchestration.

Converts raw UserInput into the (input, config, context) triple required by
the supervisor agent via ``create_agent()``.

This is a pure utility module with no side effects or external dependencies
beyond LangChain types and schemas.
"""

import logging
from typing import TypedDict
from uuid import UUID

from langchain_core.messages import HumanMessage
from langchain_core.runnables import RunnableConfig

from app.agents.context import AgentRuntimeContext
from app.schemas.chat import UserInput
from app.utils.logging import request_id_context, thread_id_context

logger = logging.getLogger(__name__)


class AgentKwargs(TypedDict):
    """The (input, config, context) triple consumed by supervisor.invoke/astream."""

    input: dict[str, list[HumanMessage]]
    config: RunnableConfig
    context: AgentRuntimeContext


def _build_context(
    user_input: UserInput,
    user_id: UUID,
    request_id: str,
) -> AgentRuntimeContext:
    """Build an AgentRuntimeContext from user input and extracted parameters.

    All fields have safe defaults — the context is always valid even when
    optional UserInput fields are None.
    """
    custom = user_input.custom_data or {}
    return AgentRuntimeContext(
        user_id=user_id,
        request_id=request_id,
        model_name=user_input.model_name or "",
        thinking_mode=bool(user_input.thinking_mode),
        timezone=user_input.timezone or "Asia/Shanghai",
        file=str(custom.get("file", "")),
    )


async def build_agent_kwargs(
    user_input: UserInput,
    thread_id: str,
    user_id: UUID,
    request_id: str,
) -> AgentKwargs:
    """Convert UserInput to parameters for supervisor.invoke/astream.

    Two channels for passing runtime data:

    - ``config["configurable"]``: Contains only ``thread_id``, which is read by
      LangGraph checkpointer as its internal convention. No business data is stored here.

    - ``context`` (AgentRuntimeContext dataclass): All business/runtime fields —
      ``user_id``, ``request_id``, ``model_name``, ``thinking_mode``.
      Middleware reads these fields via ``request.runtime.context.<field>``
      (LangChain v1 official recommended pattern).

    ``custom_data`` is stored in ``HumanMessage.additional_kwargs`` for persistence
    and restored when loading history.
    """
    # configurable only stores thread_id — LangGraph checkpointer convention
    config = RunnableConfig(configurable={"thread_id": thread_id})

    # Build HumanMessage, store custom_data in additional_kwargs for persistence
    human_message = HumanMessage(content=user_input.content)
    if user_input.custom_data:
        human_message.additional_kwargs["custom_data"] = user_input.custom_data

    input_data: dict[str, list] = {
        "messages": [human_message],
    }

    context = _build_context(user_input, user_id, request_id)

    # Set context variables so all downstream log records automatically
    # include request_id and thread_id (via RequestIdFilter on root logger).
    request_id_context.set(request_id or "-")
    thread_id_context.set(thread_id or "-")

    logger.info(
        "build_agent_kwargs: thinking_mode=%s, model_name=%s, has_custom_data=%s",
        user_input.thinking_mode,
        user_input.model_name,
        bool(user_input.custom_data),
    )

    return {
        "input": input_data,
        "config": config,
        "context": context,
    }
