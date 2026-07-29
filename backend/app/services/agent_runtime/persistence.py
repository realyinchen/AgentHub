from __future__ import annotations

import logging
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.runnables import RunnableConfig
from langgraph.graph.state import CompiledStateGraph
from sqlalchemy.ext.asyncio import AsyncSession

from app.crud.trace import persist_agent_trace
from app.infra.database import get_database
from app.schemas.chat import ChatMessage, UserInput
from app.services.agent_runtime.contracts import ActionPlan, PlanReceipt
from app.services.agent_runtime.finalizer import receipt_trace_steps
from app.services.agent_runtime.execution_graph import build_execution_graph


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
    """Persist a runtime-finalized answer and project receipts into its trace."""

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
    persisted_messages: list[Any] = [
        human_message,
        AIMessage(
            content=message.content,
            additional_kwargs={"custom_data": message.custom_data},
        ),
    ]
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
            system_tool_steps=receipt_trace_steps(receipt, plan=plan),
            system_execution_graph=build_execution_graph(plan, receipt),
        )

    if db is not None:
        await persist(db)
        return
    database = get_database()
    async with database.session() as session:
        await persist(session)
