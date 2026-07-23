from __future__ import annotations

import logging
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from langgraph.graph.state import CompiledStateGraph
from sqlalchemy.ext.asyncio import AsyncSession

from app.crud.trace import persist_agent_trace
from app.infra.database import get_database
from app.schemas.chat import ChatMessage, UserInput
from app.services.agent_runtime.contracts import ActionPlan, PlanReceipt
from app.services.agent_runtime.finalizer import receipt_tool_info


logger = logging.getLogger(__name__)


async def persist_runtime_finalized_turn(
    *,
    agent: CompiledStateGraph,
    user_input: UserInput,
    message: ChatMessage,
    plan: ActionPlan,
    receipt: PlanReceipt,
    db: AsyncSession | None = None,
) -> None:
    """Persist deterministic answers as plan -> receipt -> answer messages."""

    config = RunnableConfig(
        {"configurable": {"thread_id": str(user_input.thread_id)}}
    )
    before_checkpoint_id: str | None = None
    before_message_count = 0
    try:
        before_state = await agent.aget_state(config)
        before_message_count = len(before_state.values.get("messages", []))
        configurable = before_state.config.get("configurable") or {}
        before_checkpoint_id = configurable.get("checkpoint_id")
    except Exception as exc:
        logger.debug("Runtime finalizer could not read prior state: %s", exc)

    human_message = HumanMessage(content=user_input.content)
    if user_input.custom_data:
        human_message.additional_kwargs["custom_data"] = user_input.custom_data
    persisted_messages: list[Any] = [human_message]
    for item in receipt_tool_info(receipt):
        tool_name = str(item.get("name") or "runtime")
        tool_id = str(item.get("id") or "runtime-action")
        tool_args = item.get("args") if isinstance(item.get("args"), dict) else {}
        persisted_messages.extend(
            [
                AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "name": tool_name,
                            "args": tool_args,
                            "id": tool_id,
                            "type": "tool_call",
                        }
                    ],
                    additional_kwargs={
                        "custom_data": {
                            "action_plan": plan.model_dump(mode="json"),
                            "plan_id": plan.plan_id,
                        }
                    },
                ),
                ToolMessage(
                    content=str(item.get("output") or ""),
                    tool_call_id=tool_id,
                    name=tool_name,
                    additional_kwargs={
                        "custom_data": {
                            "plan_receipt": receipt.model_dump(mode="json"),
                            "plan_id": plan.plan_id,
                        }
                    },
                ),
            ]
        )
    persisted_messages.append(
        AIMessage(
            content=message.content,
            additional_kwargs={"custom_data": message.custom_data},
        )
    )
    await agent.aupdate_state(
        config,
        {"messages": persisted_messages},
        as_node="model",
    )

    async def persist(session: AsyncSession) -> None:
        await persist_agent_trace(
            db=session,
            agent=agent,
            thread_id=user_input.thread_id,
            request_id=user_input.request_id,
            model_name=None,
            tokens={"input_tokens": 0, "output_tokens": 0, "total_tokens": 0},
            before_checkpoint_id=before_checkpoint_id,
            before_message_count=before_message_count,
        )

    if db is not None:
        await persist(db)
        return
    database = get_database()
    async with database.session() as session:
        await persist(session)
