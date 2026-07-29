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
from app.services.agent_runtime.execution_graph import (
    EXECUTION_GRAPH_CONTRACT_VERSION,
    ExecutionGraph,
    ExecutionGraphEdge,
    ExecutionGraphNode,
    build_execution_graph,
)
from app.services.agent_runtime.failure_projection import (
    RuntimeFailureSummary,
    project_runtime_failure,
    render_research_failure,
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
    "EXECUTION_GRAPH_CONTRACT_VERSION",
    "ExecutionGraph",
    "ExecutionGraphEdge",
    "ExecutionGraphNode",
    "RuntimeFailureSummary",
    "build_execution_graph",
    "build_fast_action_plan",
    "finalize_deterministic_receipt",
    "finalize_runtime_receipt",
    "prepare_runtime_turn",
    "project_runtime_failure",
    "render_research_failure",
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
    if name in {"finalize_deterministic_receipt", "finalize_runtime_receipt"}:
        from app.services.agent_runtime.finalizer import (
            finalize_deterministic_receipt,
            finalize_runtime_receipt,
        )

        return {
            "finalize_deterministic_receipt": finalize_deterministic_receipt,
            "finalize_runtime_receipt": finalize_runtime_receipt,
        }[name]
    raise AttributeError(name)
