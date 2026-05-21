"""Request → Agent Parameter Orchestration Layer.

Convert raw UserInput into the (input, config, context) triple required by create_agent.
When extending new Agents in the future, simply add the corresponding builder function
in this module and dispatch by agent_id, no need to modify the routing layer.
"""

import logging
from typing import Any

from langchain_core.messages import HumanMessage
from langchain_core.runnables import RunnableConfig

from app.agents.chatbot.types import ChatbotContext
from app.schemas.chat import UserInput

logger = logging.getLogger(__name__)


async def build_agent_kwargs(user_input: UserInput) -> dict[str, Any]:
    """Convert UserInput to parameters for agent.invoke/astream.

    Two channels for passing runtime data:

    - ``config["configurable"]``: Contains only ``thread_id``, which is read by
      LangGraph checkpointer as its internal convention. No business data is stored here.

    - ``context`` (ChatbotContext dataclass): All business/runtime fields —
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

    # Build ChatbotContext — middleware reads via request.runtime.context
    context = ChatbotContext(
        user_id=user_input.user_id or "",
        request_id=user_input.request_id or "",
        model_name=user_input.model_name or "",
        thinking_mode=bool(user_input.thinking_mode),
        timezone=user_input.timezone or "Asia/Shanghai",
    )

    logger.info(
        "[request_id=%s][user_id=%s][thread_id=%s] build_agent_kwargs: "
        "thinking_mode=%s, model_name=%s, has_custom_data=%s",
        user_input.request_id,
        user_input.user_id,
        thread_id,
        user_input.thinking_mode,
        user_input.model_name,
        bool(user_input.custom_data),
    )

    return {
        "input": input_data,
        "config": config,
        "context": context,
    }
