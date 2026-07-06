"""Request → Agent parameter orchestration.

Converts raw UserInput into the (input, config, context) triple required by
the supervisor agent via ``create_agent()``.

This is a pure utility module with no side effects or external dependencies
beyond LangChain types and schemas.
"""

import logging
from typing import TypedDict

from langchain_core.messages import HumanMessage
from langchain_core.runnables import RunnableConfig

from app.agents.context import AgentRuntimeContext
from app.schemas.chat import UserInput
from app.utils.logging import request_id_context
from app.utils.turn_context import current_user_message_context

logger = logging.getLogger(__name__)


class AgentKwargs(TypedDict):
    """The (input, config, context) triple consumed by supervisor.invoke/astream."""

    input: dict[str, list[HumanMessage]]
    config: RunnableConfig
    context: AgentRuntimeContext


def _build_context(user_input: UserInput) -> AgentRuntimeContext:
    """Build an AgentRuntimeContext from user input.

    All fields have safe defaults — the context is always valid even when
    optional UserInput fields are None.
    """
    custom = user_input.custom_data or {}
    return AgentRuntimeContext(
        user_id=user_input.user_id or "",
        thread_id=user_input.thread_id,
        request_id=user_input.request_id or "",
        model_name=user_input.model_uuid or user_input.model_name or "",
        thinking_mode=bool(user_input.thinking_mode),
        timezone=user_input.timezone or "Asia/Shanghai",
        file=str(custom.get("file", "")),
    )


async def build_agent_kwargs(user_input: UserInput) -> AgentKwargs:
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
    thread_id = str(user_input.thread_id)

    # configurable only stores thread_id — LangGraph checkpointer convention
    config = RunnableConfig(configurable={"thread_id": thread_id})

    # Build HumanMessage, store custom_data in additional_kwargs for persistence
    human_message = HumanMessage(content=user_input.content)
    if user_input.custom_data:
        human_message.additional_kwargs["custom_data"] = user_input.custom_data

    input_data: dict[str, list] = {
        "messages": [human_message],
    }

    context = _build_context(user_input)

    # Set request_id context variable so all downstream log records
    # automatically include it (via RequestIdFilter on root logger).
    request_id_context.set(user_input.request_id or "-")
    current_user_message_context.set(user_input.content or "")

    logger.info(
        "build_agent_kwargs: thread_id=%s, thinking_mode=%s, model_key=%s, has_custom_data=%s",
        thread_id,
        user_input.thinking_mode,
        user_input.model_uuid or user_input.model_name,
        bool(user_input.custom_data),
    )

    return {
        "input": input_data,
        "config": config,
        "context": context,
    }
