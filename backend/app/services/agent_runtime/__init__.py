"""App-owned Agent Runtime contracts and lazy public exports."""

from __future__ import annotations

from typing import Any

from app.services.agent_runtime.contracts import (
    ACTION_PLAN_CONTRACT_VERSION,
    PLAN_RECEIPT_CONTRACT_VERSION,
    ActionPlan,
    ActionReceipt,
    ExecutionContext,
    PlanReceipt,
    PlannedAction,
    PreparedRuntimeTurn,
)

__all__ = [
    "ACTION_PLAN_CONTRACT_VERSION",
    "PLAN_RECEIPT_CONTRACT_VERSION",
    "ActionPlan",
    "ActionPlanner",
    "ActionReceipt",
    "ExecutionContext",
    "PlanReceipt",
    "PlannedAction",
    "PreparedRuntimeTurn",
    "SystemRuntime",
    "build_fast_action_plan",
    "finalize_deterministic_receipt",
    "prepare_runtime_turn",
]


def __getattr__(name: str) -> Any:
    if name in {"ActionPlanner", "build_fast_action_plan"}:
        from app.services.agent_runtime.planner import (
            ActionPlanner,
            build_fast_action_plan,
        )

        return {
            "ActionPlanner": ActionPlanner,
            "build_fast_action_plan": build_fast_action_plan,
        }[name]
    if name == "SystemRuntime":
        from app.services.agent_runtime.runtime import SystemRuntime

        return SystemRuntime
    if name == "prepare_runtime_turn":
        from app.services.agent_runtime.coordinator import prepare_runtime_turn

        return prepare_runtime_turn
    if name == "finalize_deterministic_receipt":
        from app.services.agent_runtime.finalizer import finalize_deterministic_receipt

        return finalize_deterministic_receipt
    raise AttributeError(name)
