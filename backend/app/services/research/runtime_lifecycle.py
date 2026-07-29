from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from app.services.agent_runtime.contracts import (
    ActionPlan,
    ExecutionContext,
    PlanReceipt,
)


logger = logging.getLogger(__name__)


async def close_interrupted_research_run(
    *,
    plan: ActionPlan,
    receipt: PlanReceipt,
    context: ExecutionContext,
) -> None:
    """Close a started run when the bounded workflow cannot reach publication."""

    operations = {action.operation for action in plan.actions}
    if "start_research" not in operations or "publish_research_answer" not in operations:
        return
    published = next(
        (
            action
            for action in receipt.actions
            if action.operation == "publish_research_answer"
            and action.status == "completed"
        ),
        None,
    )
    if published is not None:
        return

    start = next(
        (
            action
            for action in receipt.actions
            if action.operation == "start_research"
            and action.status == "completed"
            and isinstance(action.output, dict)
        ),
        None,
    )
    run_id = _run_id(start.output if start is not None else {})
    if not run_id:
        return

    from app.services.research.orchestrator import get_research_orchestrator

    try:
        await get_research_orchestrator().finish_research(
            user_id=context.user_id,
            run_id=UUID(run_id),
            conclusion=(
                "研究执行未能到达发布节点；运行已终结，未生成未经验证的结论。"
            ),
            status="failed",
            gaps=["research_workflow_interrupted"],
            metadata={
                "plan_id": plan.plan_id,
                "plan_status": receipt.status,
                "terminal_guard": True,
            },
        )
    except ValueError as exc:
        if "not active" not in str(exc).lower():
            logger.warning("Unable to close research run %s: %s", run_id, exc)
    except Exception as exc:  # pragma: no cover - lifecycle must not hide receipt
        logger.warning("Unable to close research run %s: %s", run_id, exc)


def _run_id(output: dict[str, Any]) -> str:
    for path in (
        ("run", "id"),
        ("state", "run_id"),
        ("run_id",),
        ("id",),
        ("research_state", "run", "id"),
        ("research_state", "state", "run_id"),
    ):
        current: Any = output
        for key in path:
            if not isinstance(current, dict):
                current = None
                break
            current = current.get(key)
        if current:
            return str(current)
    return ""
