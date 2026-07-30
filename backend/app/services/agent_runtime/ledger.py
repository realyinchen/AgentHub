from __future__ import annotations

import hashlib
import json
from typing import Protocol

from app.services.agent_runtime.contracts import (
    ActionPlan,
    ActionReceipt,
    ExecutionContext,
    PlannedAction,
)


class ExecutionLedger(Protocol):
    async def get(
        self,
        *,
        plan: ActionPlan,
        action: PlannedAction,
        context: ExecutionContext,
    ) -> ActionReceipt | None: ...

    async def record(
        self,
        *,
        plan: ActionPlan,
        action: PlannedAction,
        context: ExecutionContext,
        receipt: ActionReceipt,
    ) -> ActionReceipt: ...


def action_idempotency_key(
    *,
    plan: ActionPlan,
    action: PlannedAction,
    context: ExecutionContext,
) -> str:
    scope = (
        {
            "kind": "task",
            "task_id": str(context.task_id),
            "plan_version_id": str(context.plan_version_id),
            "action_id": action.action_id,
        }
        if context.task_id is not None
        else {
            "kind": "turn",
            "user_id": str(context.user_id),
            "thread_id": str(context.thread_id or ""),
            "request_id": context.request_id,
            "plan_id": plan.plan_id,
            "action_id": action.action_id,
        }
    )
    return hashlib.sha256(
        json.dumps(
            scope,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


__all__ = ["ExecutionLedger", "action_idempotency_key"]
