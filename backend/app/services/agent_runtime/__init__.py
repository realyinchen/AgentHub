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
from app.services.agent_runtime.ledger import (
    ExecutionLedger,
    action_idempotency_key,
)

__all__ = [
    "ACTION_PLAN_CONTRACT_VERSION",
    "PLAN_RECEIPT_CONTRACT_VERSION",
    "ActionPlan",
    "ActionReceipt",
    "ExecutionContext",
    "ExecutionLedger",
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
    "action_idempotency_key",
    "finalize_deterministic_receipt",
    "finalize_runtime_receipt",
    "project_runtime_failure",
    "render_research_failure",
]


def __getattr__(name: str) -> Any:
    if name == "SystemRuntime":
        from app.services.agent_runtime.runtime import SystemRuntime

        return SystemRuntime
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
