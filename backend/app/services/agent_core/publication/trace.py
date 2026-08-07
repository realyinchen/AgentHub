from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.crud.trace import upsert_trace
from app.schemas.chat import ChatMessage, UserInput
from app.schemas.trace import ExecutionDag, StepOutput
from app.services.agent_runtime.execution_graph import ExecutionGraph


async def persist_publication_trace(
    db: AsyncSession,
    *,
    user_input: UserInput,
    message: ChatMessage,
    graph: ExecutionGraph,
    model_name: str,
) -> None:
    """Persist a redacted trace projected only from the trusted graph."""

    if user_input.thread_id is None:
        raise ValueError("publication trace requires a thread_id")
    steps: list[StepOutput] = [
        StepOutput(
            step_number=1,
            message_type="human",
            content=user_input.content,
        )
    ]
    for node in sorted(graph.nodes, key=lambda item: item.order):
        if node.kind != "action":
            continue
        steps.append(
            StepOutput(
                step_number=node.step_number,
                message_type="tool",
                content=None,
                tool_name=node.operation or node.label,
                tool_args=node.metadata.get("tool_args"),
                tool_output=None,
                tool_call_id=node.action_id,
                system_executed=bool(
                    node.metadata.get("system_executed")
                ),
                tool_status=node.status,
                tool_error=None,
                latency_ms=None,
                action_id=node.action_id,
                depends_on=[],
            )
        )
    steps.append(
        StepOutput(
            step_number=len(graph.nodes),
            message_type="ai",
            content=message.content,
            model_name=model_name or None,
        )
    )
    dag = ExecutionDag(
        thread_id=str(user_input.thread_id),
        nodes=[],
        edges=[],
        total_steps=len(steps),
        steps=steps,
        execution_graph=graph,
    )
    await upsert_trace(
        db=db,
        thread_id=user_input.thread_id,
        request_id=user_input.request_id,
        dag_data=dag.model_dump(mode="json"),
        total_steps=len(steps),
        model_name=model_name or None,
    )


__all__ = ["persist_publication_trace"]
