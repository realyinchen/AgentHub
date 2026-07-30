from __future__ import annotations

from dataclasses import dataclass

from app.services.agent_core.contracts import CapabilityProposalBatch
from app.services.agent_runtime.contracts import (
    ActionPlan,
    PlannedAction,
    PlanSource,
    ResponseMode,
)
from app.services.external_capabilities.operation_registry import (
    descriptor_for_capability,
)


class WorkflowCompiler:
    """Compile validated high-level capabilities into one ActionPlan."""

    def compile(
        self,
        batch: CapabilityProposalBatch,
        *,
        goal: str,
        source: PlanSource = "controller_proposal",
    ) -> ActionPlan:
        if not batch.proposals:
            raise ValueError("cannot compile an empty capability batch")

        actions: list[PlannedAction] = []
        response_modes: list[ResponseMode] = []
        for proposal in batch.proposals:
            compiled = compile_capability(proposal.capability)
            response_modes.append(compiled.response_mode)
            actions.append(
                PlannedAction(
                    action_id=_action_id(proposal.call_id),
                    capability=compiled.domain,
                    operation=compiled.operation,
                    arguments=dict(proposal.arguments),
                    reason=compiled.reason,
                    depends_on=[
                        _action_id(item) for item in proposal.depends_on
                    ],
                    metadata={
                        "controller_call_id": proposal.call_id,
                        "high_level_capability": proposal.capability,
                    },
                )
            )

        return ActionPlan(
            source=source,
            route_type="fast_path",
            intent="controller_capability_batch",
            goal=goal,
            confidence=1.0,
            complexity="low",
            planner_used=True,
            response_mode=(
                "model" if "model" in response_modes else "receipt"
            ),
            actions=actions,
            metadata={
                "agent_core_contract": batch.contract_version,
                "compiled_from": "validated_capability_proposals",
            },
        )


@dataclass(frozen=True)
class CompiledCapability:
    operation: str
    domain: str
    reason: str
    response_mode: ResponseMode = "receipt"


def compile_capability(name: str) -> CompiledCapability:
    external = descriptor_for_capability(name)
    if external is not None:
        return CompiledCapability(
            operation=external.operation,
            domain=external.domain,
            reason=external.reason,
            response_mode=external.response_mode,
        )
    compiled = {
        "conversation_read": CompiledCapability(
            operation="conversation_read",
            domain="conversation",
            reason="Read exact role-aware recent conversation state.",
        ),
        "remember_memory": CompiledCapability(
            operation="remember_memory_v2",
            domain="memory",
            reason="Commit only system-canonicalized user facts.",
        ),
        "search_memory": CompiledCapability(
            operation="search_memory_v2",
            domain="memory",
            reason="Read only current canonical memory heads.",
        ),
        "forget_memory": CompiledCapability(
            operation="forget_memory_v2",
            domain="memory",
            reason="Create a chain tombstone for resolved facts.",
        ),
        "cancel_active_task": CompiledCapability(
            operation="cancel_active_task_v1",
            domain="task",
            reason="Cancel only the conversation's system-resolved active task.",
        ),
    }.get(name)
    if compiled is None:
        raise ValueError(f"no compiler registered for {name}")
    return compiled


def _action_id(call_id: str) -> str:
    return f"controller-action-{call_id}"


__all__ = [
    "CompiledCapability",
    "WorkflowCompiler",
    "compile_capability",
]
