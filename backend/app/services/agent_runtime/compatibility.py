"""Narrow opt-in port for executing quarantined pre-Agent plans."""

from __future__ import annotations

from typing import Any, Protocol

from app.schemas.chat import UserInput
from app.services.agent_runtime.contracts import (
    ActionPlan,
    ActionReceipt,
    ExecutionContext,
    PlannedAction,
)


class RuntimeCompatibilityPort(Protocol):
    """Compatibility behavior injected explicitly by a migration boundary."""

    def handles(self, plan: ActionPlan, action: PlannedAction) -> bool: ...

    def admit(
        self,
        plan: ActionPlan,
        action: PlannedAction,
    ) -> tuple[bool, str]: ...

    async def execute(
        self,
        plan: ActionPlan,
        action: PlannedAction,
        *,
        context: ExecutionContext,
        user_input: UserInput | None,
        previous: list[ActionReceipt],
    ) -> Any: ...

    def injected_fields(
        self,
        action: PlannedAction,
        context: ExecutionContext,
    ) -> tuple[str, ...]: ...


class DisabledRuntimeCompatibility:
    """Default port: no retired plan source or operation is executable."""

    def handles(self, plan: ActionPlan, action: PlannedAction) -> bool:
        del plan, action
        return False

    def admit(
        self,
        plan: ActionPlan,
        action: PlannedAction,
    ) -> tuple[bool, str]:
        del plan, action
        return False, "runtime_compatibility_disabled"

    async def execute(
        self,
        plan: ActionPlan,
        action: PlannedAction,
        *,
        context: ExecutionContext,
        user_input: UserInput | None,
        previous: list[ActionReceipt],
    ) -> Any:
        del plan, action, context, user_input, previous
        raise RuntimeError("runtime_compatibility_disabled")

    def injected_fields(
        self,
        action: PlannedAction,
        context: ExecutionContext,
    ) -> tuple[str, ...]:
        del action, context
        return ()


__all__ = ["DisabledRuntimeCompatibility", "RuntimeCompatibilityPort"]
