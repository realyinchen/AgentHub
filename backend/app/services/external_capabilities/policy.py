from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping


@dataclass(frozen=True)
class CapabilityRuntimePolicy:
    timeout_seconds: float
    max_attempts: int = 1

    def __post_init__(self) -> None:
        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        if self.max_attempts < 1 or self.max_attempts > 3:
            raise ValueError("max_attempts must be between 1 and 3")


_DEFAULT_POLICIES = MappingProxyType(
    {
        "weather_get_v1": CapabilityRuntimePolicy(
            timeout_seconds=12.0,
            max_attempts=1,
        ),
        "web_search_v2": CapabilityRuntimePolicy(
            timeout_seconds=20.0,
            max_attempts=1,
        ),
        "book_search_v1": CapabilityRuntimePolicy(
            timeout_seconds=25.0,
            max_attempts=1,
        ),
        "research_prepare_v1": CapabilityRuntimePolicy(
            timeout_seconds=5.0,
            max_attempts=1,
        ),
        "research_search_v1": CapabilityRuntimePolicy(
            timeout_seconds=120.0,
            max_attempts=1,
        ),
        "research_admit_evidence_v1": CapabilityRuntimePolicy(
            timeout_seconds=5.0,
            max_attempts=1,
        ),
        "research_report_v1": CapabilityRuntimePolicy(
            timeout_seconds=5.0,
            max_attempts=1,
        ),
    }
)


class ExternalCapabilityPolicyRegistry:
    """Read-only lookup for bounded execution policies."""

    def __init__(
        self,
        *,
        policies: Mapping[str, CapabilityRuntimePolicy] | None = None,
    ) -> None:
        self._policies = dict(policies or _DEFAULT_POLICIES)

    def require(self, operation: str) -> CapabilityRuntimePolicy:
        policy = self._policies.get(str(operation or "").strip())
        if policy is None:
            raise LookupError(
                f"external capability policy is not registered: {operation}"
            )
        return policy


__all__ = [
    "CapabilityRuntimePolicy",
    "ExternalCapabilityPolicyRegistry",
]
