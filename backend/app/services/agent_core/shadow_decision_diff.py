from __future__ import annotations

from pydantic import Field, model_validator

from app.services.agent_core.contracts import AgentCoreModel
from app.services.agent_core.shadow_evidence import hash_shadow_json
from app.services.agent_core.shadow_gate_read_contracts import (
    ShadowGateRawTurn,
)


class ShadowDecisionSignature(AgentCoreModel):
    decision_mode: str = Field(min_length=1, max_length=128)
    operations: list[str] = Field(default_factory=list, max_length=64)
    route_type: str | None = Field(default=None, max_length=128)
    intent: str | None = Field(default=None, max_length=128)


class ShadowDecisionDifference(AgentCoreModel):
    kind: str | None = Field(default=None, max_length=128)
    fingerprint: str | None = Field(
        default=None,
        pattern="^[0-9a-f]{64}$",
    )
    new_signature: ShadowDecisionSignature | None = None
    legacy_signature: ShadowDecisionSignature | None = None

    @model_validator(mode="after")
    def validate_evidence(self) -> "ShadowDecisionDifference":
        evidence = (
            self.fingerprint,
            self.new_signature,
            self.legacy_signature,
        )
        if self.kind is None and any(item is not None for item in evidence):
            raise ValueError(
                "Shadow decision evidence requires a difference kind"
            )
        if self.kind is not None and any(item is None for item in evidence):
            raise ValueError(
                "Shadow difference requires fingerprint and signatures"
            )
        return self


class ShadowDecisionDiffer:
    """Compare allowlisted new and legacy decision signatures."""

    def compare(
        self,
        turn: ShadowGateRawTurn,
    ) -> ShadowDecisionDifference:
        if turn.observation is None or len(turn.terminal_events) != 1:
            return ShadowDecisionDifference()
        new_signature = _new_signature(turn.observation)
        legacy_signature = _legacy_signature(
            turn.terminal_events[0].summary
        )
        kinds: list[str] = []
        if new_signature.decision_mode != legacy_signature.decision_mode:
            kinds.append("decision_mode")
        if new_signature.operations != legacy_signature.operations:
            kinds.append("operations")
        for field in ("route_type", "intent"):
            new_value = getattr(new_signature, field)
            old_value = getattr(legacy_signature, field)
            if new_value is not None and old_value is not None:
                if new_value != old_value:
                    kinds.append(field)
        if not kinds:
            return ShadowDecisionDifference()
        return ShadowDecisionDifference(
            kind="+".join(sorted(kinds)),
            fingerprint=hash_shadow_json(
                {
                    "new": new_signature.model_dump(mode="json"),
                    "legacy": legacy_signature.model_dump(mode="json"),
                }
            ),
            new_signature=new_signature,
            legacy_signature=legacy_signature,
        )


def _new_signature(observation) -> ShadowDecisionSignature:
    proposal = dict(observation.proposal_summary or {})
    plan = dict(observation.plan_summary or {})
    actions = plan.get("actions")
    action_items = actions if isinstance(actions, list) else []
    capabilities = proposal.get("capabilities")
    capability_items = (
        capabilities if isinstance(capabilities, list) else []
    )
    operations = [
        str(item.get("capability"))
        for item in action_items
        if isinstance(item, dict)
        and str(item.get("capability") or "").strip()
    ]
    if not operations:
        operations = [
            str(item.get("name"))
            for item in capability_items
            if isinstance(item, dict)
            and str(item.get("name") or "").strip()
        ]
    return ShadowDecisionSignature(
        decision_mode=str(proposal.get("mode") or "unknown"),
        operations=sorted(set(operations)),
        route_type=_optional_text(plan.get("route_type")),
        intent=_optional_text(plan.get("intent")),
    )


def _legacy_signature(summary: dict) -> ShadowDecisionSignature:
    terminal_kind = str(summary.get("terminal_kind") or "")
    trace_value = summary.get("runtime_trace")
    trace = trace_value if isinstance(trace_value, dict) else {}
    operations_value = summary.get("operations")
    operations = (
        operations_value if isinstance(operations_value, list) else []
    )
    if terminal_kind == "clarification_requested":
        mode = "request_clarification"
    elif terminal_kind == "turn_failed":
        mode = "turn_failed"
    elif operations:
        mode = (
            "task_plan_proposal"
            if any(
                str(item) in {"plan_task", "plan_task_v1"}
                for item in operations
            )
            else "capability_proposals"
        )
    else:
        mode = "direct_answer"
    return ShadowDecisionSignature(
        decision_mode=mode,
        operations=sorted(
            {
                str(item)
                for item in operations
                if str(item).strip()
            }
        ),
        route_type=_optional_text(trace.get("route_type")),
        intent=_optional_text(trace.get("intent")),
    )


def _optional_text(value: object) -> str | None:
    candidate = str(value or "").strip()
    return candidate or None


__all__ = [
    "ShadowDecisionDifference",
    "ShadowDecisionDiffer",
    "ShadowDecisionSignature",
]
