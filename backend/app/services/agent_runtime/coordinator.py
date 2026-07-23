from __future__ import annotations

from app.schemas.chat import UserInput
from app.services.agent_runtime.contracts import ExecutionContext, PreparedRuntimeTurn
from app.services.agent_runtime.planner import ActionPlanner
from app.services.agent_runtime.runtime import SystemRuntime


async def prepare_runtime_turn(
    user_input: UserInput,
    *,
    model_name: str = "",
) -> PreparedRuntimeTurn:
    """Plan first, execute second, and return the system receipt."""

    plan = await ActionPlanner().plan(user_input, model_name=model_name)
    context = ExecutionContext(
        user_id=user_input.user_id,
        thread_id=user_input.thread_id,
        request_id=user_input.request_id,
        model_name=model_name or user_input.model_uuid or user_input.model_name or "",
        timezone=user_input.timezone,
        metadata={
            "user_message": user_input.content,
            "plan_id": plan.plan_id,
            "route_type": plan.route_type,
            "intent": plan.intent,
            "planner_used": plan.planner_used,
        },
    )
    receipt = await SystemRuntime().execute(
        plan,
        context=context,
        user_input=user_input,
    )
    return PreparedRuntimeTurn(plan=plan, receipt=receipt)
