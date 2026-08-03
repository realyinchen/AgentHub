from __future__ import annotations

from langgraph.graph.state import CompiledStateGraph

from app.schemas.chat import UserInput
from app.services.agent_runtime.contracts import ExecutionContext, PreparedRuntimeTurn
from app.services.agent_runtime.legacy_compatibility import (
    LegacyRoutingRuntimeCompatibility,
)
from app.services.agent_runtime.planner import ActionPlanner
from app.services.agent_runtime.runtime import SystemRuntime
from app.services.routing.context import project_business_routing_context


async def prepare_legacy_runtime_turn(
    user_input: UserInput,
    *,
    model_name: str = "",
    agent: CompiledStateGraph | None = None,
) -> PreparedRuntimeTurn:
    """Plan first, execute second, and return the system receipt."""

    routing_context = await project_business_routing_context(
        user_input=user_input,
        agent=agent,
    )
    plan = await ActionPlanner().plan(
        user_input,
        model_name=model_name,
        routing_context=routing_context,
    )
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
            "conversation_turns": [
                turn.model_dump(mode="json")
                for turn in routing_context.conversation_turns
            ],
            "recent_user_messages": list(routing_context.recent_user_messages),
        },
    )
    receipt = await SystemRuntime(
        compatibility=LegacyRoutingRuntimeCompatibility(),
    ).execute(
        plan,
        context=context,
        user_input=user_input,
    )
    from app.services.research.runtime_lifecycle import (
        close_interrupted_research_run,
    )

    await close_interrupted_research_run(
        plan=plan,
        receipt=receipt,
        context=context,
    )
    return PreparedRuntimeTurn(plan=plan, receipt=receipt)


# Import compatibility for scripts outside the production entry. New runtime
# code must depend on LegacyChatRuntimeBridge instead.
prepare_runtime_turn = prepare_legacy_runtime_turn


__all__ = ["prepare_legacy_runtime_turn", "prepare_runtime_turn"]
