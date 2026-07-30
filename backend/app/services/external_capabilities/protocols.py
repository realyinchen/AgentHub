from __future__ import annotations

from typing import Any, Protocol

from app.services.agent_runtime.contracts import (
    ActionReceipt,
    ExecutionContext,
)


class ExternalCapabilityAdapter(Protocol):
    operation: str

    async def execute(
        self,
        arguments: dict[str, Any],
        *,
        context: ExecutionContext,
        previous: list[ActionReceipt],
    ) -> dict[str, Any]:
        ...


__all__ = ["ExternalCapabilityAdapter"]

