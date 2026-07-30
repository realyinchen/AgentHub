from __future__ import annotations

from app.services.agent_core.capabilities import CapabilityRegistry
from app.services.agent_core.contracts import (
    CapabilityProposalBatch,
    ControllerOutput,
    ValidatedCapabilityProposal,
)
from app.services.system_owned_fields import (
    MODEL_PROPOSAL_FORBIDDEN_FIELDS,
    find_forbidden_paths,
)


class ProposalValidator:
    """Validate model proposals without compiling or executing them."""

    def __init__(self, registry: CapabilityRegistry | None = None) -> None:
        self._registry = registry or CapabilityRegistry()

    def validate(self, output: ControllerOutput) -> CapabilityProposalBatch:
        if output.mode != "capability_proposals":
            return CapabilityProposalBatch()

        call_ids = [item.call_id for item in output.tool_calls]
        if len(call_ids) != len(set(call_ids)):
            raise ValueError("controller tool call IDs must be unique")
        known = set(call_ids)

        proposals: list[ValidatedCapabilityProposal] = []
        for call in output.tool_calls:
            invalid = sorted(
                find_forbidden_paths(
                    call.arguments,
                    forbidden_fields=MODEL_PROPOSAL_FORBIDDEN_FIELDS,
                )
            )
            if invalid:
                raise ValueError(
                    "model proposal contains system-owned fields: "
                    + ", ".join(invalid)
                )
            missing = [item for item in call.depends_on if item not in known]
            if missing:
                raise ValueError(
                    f"tool call {call.call_id} has unknown dependencies: {missing}"
                )
            if call.call_id in call.depends_on:
                raise ValueError(
                    f"tool call {call.call_id} cannot depend on itself"
                )

            spec = self._registry.require_enabled(call.name)
            payload = spec.input_model.model_validate(call.arguments)
            proposals.append(
                ValidatedCapabilityProposal(
                    call_id=call.call_id,
                    capability=spec.name,
                    arguments=payload.model_dump(mode="json"),
                    depends_on=list(call.depends_on),
                    side_effect=spec.side_effect,
                )
            )
        return CapabilityProposalBatch(proposals=proposals)
