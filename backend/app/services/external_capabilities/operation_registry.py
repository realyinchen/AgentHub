from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class ExternalCapabilityDescriptor:
    capability: str
    operation: str
    domain: str
    reason: str
    response_mode: Literal["model"]


_DESCRIPTORS = (
    ExternalCapabilityDescriptor(
        capability="weather_get",
        operation="weather_get_v1",
        domain="weather",
        reason="Retrieve current weather evidence through an app-owned adapter.",
        response_mode="model",
    ),
    ExternalCapabilityDescriptor(
        capability="web_search",
        operation="web_search_v2",
        domain="external_search",
        reason="Retrieve current web evidence through an app-owned adapter.",
        response_mode="model",
    ),
    ExternalCapabilityDescriptor(
        capability="book_search",
        operation="book_search_v1",
        domain="books",
        reason="Retrieve book candidates through an app-owned adapter.",
        response_mode="model",
    ),
    ExternalCapabilityDescriptor(
        capability="research_start",
        operation="research_report_v1",
        domain="research",
        reason="Start an app-owned evidence-bounded research workflow.",
        response_mode="model",
    ),
)
_BY_CAPABILITY = {item.capability: item for item in _DESCRIPTORS}
_BY_OPERATION = {item.operation: item for item in _DESCRIPTORS}
_RESEARCH_DESCRIPTOR = _BY_CAPABILITY["research_start"]
for _operation in (
    "research_prepare_v1",
    "research_search_v1",
    "research_admit_evidence_v1",
    "research_report_v1",
):
    _BY_OPERATION[_operation] = _RESEARCH_DESCRIPTOR


def descriptor_for_capability(
    capability: str,
) -> ExternalCapabilityDescriptor | None:
    return _BY_CAPABILITY.get(str(capability or "").strip())


def descriptor_for_operation(
    operation: str,
) -> ExternalCapabilityDescriptor | None:
    return _BY_OPERATION.get(str(operation or "").strip())


__all__ = [
    "ExternalCapabilityDescriptor",
    "descriptor_for_capability",
    "descriptor_for_operation",
]
