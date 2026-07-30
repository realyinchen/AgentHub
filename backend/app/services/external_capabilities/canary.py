from __future__ import annotations

from typing import Any, Literal

from pydantic import Field

from app.services.agent_core.capabilities import CapabilityRegistry
from app.services.agent_core.compiler import WorkflowCompiler
from app.services.agent_core.contracts import (
    AgentCoreModel,
    ControllerOutput,
    ControllerToolCall,
)
from app.services.agent_core.plan_graph import PlanGraphNormalizer
from app.services.agent_core.prompt_contracts import ControllerModelRequest
from app.services.agent_core.proposal_validator import ProposalValidator
from app.services.agent_runtime.contracts import (
    ActionPlan,
    ExecutionContext,
)
from app.services.agent_runtime.runtime import SystemRuntime


class CapabilityCanarySpec(AgentCoreModel):
    capability: Literal[
        "weather_get",
        "web_search",
        "book_search",
        "research_start",
    ]
    operation: str
    expected_operations: list[str] = Field(default_factory=list)
    user_message: str
    arguments: dict[str, Any]
    expected_result_mode: str


class CapabilityCanaryRun(AgentCoreModel):
    model_phase_status: Literal["passed", "failed"]
    runtime_phase_status: Literal["passed", "failed"]
    runtime_input_source: Literal["model_proposal", "registered_fixture"]
    controller_mode: str
    proposed_capabilities: list[str] = Field(default_factory=list)
    compiled_operations: list[str] = Field(default_factory=list)
    plan_status: str = ""
    source_count: int = Field(default=0, ge=0)
    runtime_output: dict[str, Any] = Field(default_factory=dict)
    model_failure_code: str = ""
    runtime_failure_code: str = ""


async def run_capability_canary(
    *,
    spec: CapabilityCanarySpec,
    controller: Any,
    registry: CapabilityRegistry,
    request: ControllerModelRequest,
    runtime: SystemRuntime,
    context: ExecutionContext,
) -> CapabilityCanaryRun:
    """Run model and provider phases independently without faking E2E success."""

    validator = ProposalValidator(registry)
    compiler = WorkflowCompiler()
    normalizer = PlanGraphNormalizer()
    model_status: Literal["passed", "failed"] = "failed"
    model_failure = ""
    controller_mode = "error"
    proposed: list[str] = []
    plan: ActionPlan | None = None
    input_source: Literal["model_proposal", "registered_fixture"]

    try:
        output = await controller.decide(request)
        controller_mode = output.mode
        batch = validator.validate(output)
        proposed = [item.capability for item in batch.proposals]
        candidate = normalizer.normalize(
            compiler.compile(batch, goal=spec.user_message)
        )
        operations = [item.operation for item in candidate.actions]
        expected_operations = (
            spec.expected_operations or [spec.operation]
        )
        if (
            proposed != [spec.capability]
            or operations != expected_operations
        ):
            model_failure = "model_proposal_mismatch"
        else:
            model_status = "passed"
            plan = candidate
    except Exception as exc:
        model_failure = _failure_code(exc)

    if plan is None:
        input_source = "registered_fixture"
        fixture = ControllerOutput(
            mode="capability_proposals",
            tool_calls=[
                ControllerToolCall(
                    call_id="registered-canary-fixture",
                    name=spec.capability,
                    arguments=spec.arguments,
                )
            ],
        )
        batch = validator.validate(fixture)
        plan = normalizer.normalize(
            compiler.compile(batch, goal=spec.user_message)
        )
    else:
        input_source = "model_proposal"

    receipt = await runtime.execute(plan, context=context)
    operations = [item.operation for item in plan.actions]
    outputs = [
        item.output
        for item in receipt.actions
        if item.operation == spec.operation and isinstance(item.output, dict)
    ]
    payload = outputs[-1] if outputs else {}
    source_count = len(payload.get("sources", []))
    runtime_passed = (
        receipt.status == "completed"
        and payload.get("result_mode") == spec.expected_result_mode
        and payload.get("status") == "ok"
        and source_count > 0
    )
    return CapabilityCanaryRun(
        model_phase_status=model_status,
        runtime_phase_status="passed" if runtime_passed else "failed",
        runtime_input_source=input_source,
        controller_mode=controller_mode,
        proposed_capabilities=proposed,
        compiled_operations=operations,
        plan_status=receipt.status,
        source_count=source_count,
        runtime_output=payload,
        model_failure_code=model_failure,
        runtime_failure_code=(
            "" if runtime_passed else "runtime_provider_canary_incomplete"
        ),
    )


def _failure_code(exc: Exception) -> str:
    name = exc.__class__.__name__.casefold()
    message = str(exc).casefold()
    if "ratelimit" in name or "quota" in message or "额度不足" in message:
        return "model_provider_capacity"
    if isinstance(exc, TimeoutError) or "timeout" in name:
        return "model_provider_timeout"
    if isinstance(exc, (AssertionError, ValueError)):
        return "canary_contract_invalid"
    return "canary_execution_failed"


def contains_forbidden_keys(
    payload: Any,
    forbidden: set[str],
) -> bool:
    """Inspect structured keys without treating ordinary text as schema."""

    normalized = {str(item).casefold() for item in forbidden}
    if isinstance(payload, dict):
        for key, value in payload.items():
            if str(key).casefold() in normalized:
                return True
            if contains_forbidden_keys(value, normalized):
                return True
        return False
    if isinstance(payload, list):
        return any(
            contains_forbidden_keys(item, normalized) for item in payload
        )
    return False


__all__ = [
    "CapabilityCanaryRun",
    "CapabilityCanarySpec",
    "_failure_code",
    "contains_forbidden_keys",
    "run_capability_canary",
]
