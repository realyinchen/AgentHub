"""Explicit, settings-independent fixtures shared by Agent Core verifiers."""

from __future__ import annotations

from app.services.agent_core.capabilities import CapabilityRegistry
from app.services.agent_core.core_capabilities import (
    CoreCapabilityAvailability,
)
from app.services.agent_core.harness import AgentCoreHarness
from app.services.external_capabilities.availability import (
    ExternalCapabilityAvailability,
)
from app.services.tasks.draft_validator import TaskPlanDraftValidator
from app.services.tasks.plan_compiler import TaskPlanCompiler
from app.services.tasks.runner import TaskRunner


FIXTURE_REGISTRY_NAME = "all_enabled_explicit"


def build_verifier_registry() -> CapabilityRegistry:
    """Enable core contracts explicitly without mutating production settings."""

    return CapabilityRegistry(
        availability=ExternalCapabilityAvailability(),
        core_availability=CoreCapabilityAvailability.all_enabled(),
    )


def build_verifier_harness() -> AgentCoreHarness:
    """Build the production harness around an explicit verifier registry."""

    return AgentCoreHarness(registry=build_verifier_registry())


def build_task_plan_validator() -> TaskPlanDraftValidator:
    """Build the production validator around an explicit verifier registry."""

    return TaskPlanDraftValidator(build_verifier_registry())


def build_task_plan_compiler() -> TaskPlanCompiler:
    """Build the production compiler around an explicit verifier registry."""

    return TaskPlanCompiler(registry=build_verifier_registry())


def build_verifier_task_runner(**kwargs) -> TaskRunner:
    """Build the production runner with an explicit verifier compiler."""

    return TaskRunner(
        compiler=build_task_plan_compiler(),
        **kwargs,
    )


__all__ = [
    "FIXTURE_REGISTRY_NAME",
    "build_task_plan_compiler",
    "build_task_plan_validator",
    "build_verifier_harness",
    "build_verifier_registry",
    "build_verifier_task_runner",
]
