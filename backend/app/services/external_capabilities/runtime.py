from __future__ import annotations

import asyncio
from typing import Any

from app.services.agent_runtime.contracts import (
    ActionReceipt,
    ExecutionContext,
)
from app.services.external_capabilities.availability import (
    ExternalCapabilityAvailability,
)
from app.services.external_capabilities.operation_registry import (
    descriptor_for_operation,
)
from app.services.external_capabilities.policy import (
    ExternalCapabilityPolicyRegistry,
)
from app.services.external_capabilities.protocols import (
    ExternalCapabilityAdapter,
)


class ExternalCapabilityRuntime:
    """Admit and time-bound one registered external adapter invocation."""

    def __init__(
        self,
        *,
        availability: ExternalCapabilityAvailability | None = None,
        adapters: list[ExternalCapabilityAdapter] | None = None,
        policies: ExternalCapabilityPolicyRegistry | None = None,
    ) -> None:
        self._availability = (
            availability or ExternalCapabilityAvailability.from_settings()
        )
        self._adapters = {
            adapter.operation: adapter for adapter in (adapters or [])
        }
        self._policies = policies or ExternalCapabilityPolicyRegistry()

    def owns(self, operation: str) -> bool:
        return descriptor_for_operation(operation) is not None

    def admit(self, operation: str) -> tuple[bool, str]:
        descriptor = descriptor_for_operation(operation)
        if descriptor is None:
            return False, "external_capability_unknown"
        if not self._availability.enabled(descriptor.capability):
            return (
                False,
                f"external_capability_disabled:{descriptor.capability}",
            )
        if operation not in self._adapters:
            return False, f"external_capability_adapter_missing:{operation}"
        return True, "external_capability_enabled"

    async def execute(
        self,
        operation: str,
        arguments: dict[str, Any],
        *,
        context: ExecutionContext,
        previous: list[ActionReceipt],
    ) -> dict[str, Any]:
        admitted, reason = self.admit(operation)
        if not admitted:
            return {"status": "blocked", "error": reason}
        adapter = self._adapters[operation]
        policy = self._policies.require(operation)
        for attempt in range(1, policy.max_attempts + 1):
            try:
                return await asyncio.wait_for(
                    adapter.execute(
                        arguments,
                        context=context,
                        previous=previous,
                    ),
                    timeout=policy.timeout_seconds,
                )
            except TimeoutError:
                if attempt == policy.max_attempts:
                    return {
                        "status": "timeout",
                        "error": "external_capability_timeout",
                    }
            except Exception:
                if attempt == policy.max_attempts:
                    return {
                        "status": "unavailable",
                        "error": "external_capability_unavailable",
                    }
        return {
            "status": "unavailable",
            "error": "external_capability_unavailable",
        }


def get_external_capability_runtime() -> ExternalCapabilityRuntime:
    from app.services.external_capabilities.book import (
        BookSearchRuntimeAdapter,
    )
    from app.services.external_capabilities.weather import (
        WeatherRuntimeAdapter,
    )
    from app.services.external_capabilities.research import (
        ResearchEvidenceAdmissionAdapter,
        ResearchPrepareAdapter,
        ResearchReportAdapter,
        ResearchSearchAdapter,
    )
    from app.services.external_capabilities.web import (
        WebSearchRuntimeAdapter,
    )

    return ExternalCapabilityRuntime(
        adapters=[
            WeatherRuntimeAdapter(),
            WebSearchRuntimeAdapter(),
            BookSearchRuntimeAdapter(),
            ResearchPrepareAdapter(),
            ResearchSearchAdapter(),
            ResearchEvidenceAdmissionAdapter(),
            ResearchReportAdapter(),
        ]
    )


__all__ = [
    "ExternalCapabilityRuntime",
    "get_external_capability_runtime",
]
