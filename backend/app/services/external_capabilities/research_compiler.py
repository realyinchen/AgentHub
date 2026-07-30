from __future__ import annotations

from app.services.agent_core.contracts import ValidatedCapabilityProposal
from app.services.agent_runtime.contracts import PlannedAction


RESEARCH_STAGE_NAMES = (
    "prepare",
    "search",
    "admit",
    "report",
)
RESEARCH_STAGE_OPERATIONS = (
    "research_prepare_v1",
    "research_search_v1",
    "research_admit_evidence_v1",
    "research_report_v1",
)


def compile_research_workflow(
    proposal: ValidatedCapabilityProposal,
    *,
    depends_on: list[str],
) -> list[PlannedAction]:
    """Expand one semantic proposal into a continuous app-owned graph."""

    actions: list[PlannedAction] = []
    previous = list(depends_on)
    for stage, operation in zip(
        RESEARCH_STAGE_NAMES,
        RESEARCH_STAGE_OPERATIONS,
        strict=True,
    ):
        action_id = research_action_id(proposal.call_id, stage)
        arguments = (
            dict(proposal.arguments)
            if stage == "prepare"
            else {
                "max_sources": int(
                    proposal.arguments.get("max_sources") or 8
                )
            }
            if stage == "admit"
            else {}
        )
        actions.append(
            PlannedAction(
                action_id=action_id,
                capability="research",
                operation=operation,
                arguments=arguments,
                reason={
                    "prepare": "Prepare a bounded research search plan.",
                    "search": "Retrieve candidate public research sources.",
                    "admit": "Admit only safe, attributable evidence.",
                    "report": "Build a report only from admitted evidence.",
                }[stage],
                depends_on=previous,
                metadata={
                    "controller_call_id": proposal.call_id,
                    "high_level_capability": proposal.capability,
                    "research_stage": stage,
                    "side_effect": False,
                },
            )
        )
        previous = [action_id]
    return actions


def research_action_id(call_id: str, stage: str) -> str:
    return f"controller-action-{call_id}-{stage}"


def research_terminal_action_id(call_id: str) -> str:
    return research_action_id(call_id, "report")


__all__ = [
    "RESEARCH_STAGE_NAMES",
    "RESEARCH_STAGE_OPERATIONS",
    "compile_research_workflow",
    "research_action_id",
    "research_terminal_action_id",
]
