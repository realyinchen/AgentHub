from __future__ import annotations

from typing import Any
from uuid import UUID

from app.services.agent_core.certification_contracts import (
    AGENT_CERTIFICATION_CONTRACT_VERSION,
)
from app.services.agent_core.contracts import (
    AGENT_CORE_CONTRACT_VERSION,
)
from app.services.agent_core.gateway import AgentControllerAttempt
from app.services.agent_core.prompt_composer import (
    CONTROLLER_PROMPT_VERSION,
)
from app.services.agent_core.shadow_dispatcher import (
    ShadowControllerCommand,
)
from app.services.agent_core.shadow_evidence import (
    hash_shadow_json,
    hash_shadow_text,
)
from app.services.agent_core.shadow_observation_key import (
    shadow_observation_key,
)
from app.services.agent_core.shadow_observation_contracts import (
    ShadowObservationAppend,
)


class ShadowObservationProjector:
    """Project a Shadow result into de-identified append-only telemetry."""

    def project(
        self,
        command: ShadowControllerCommand,
        attempt: AgentControllerAttempt,
        *,
        latency_ms: int,
    ) -> ShadowObservationAppend:
        if attempt.mode != "shadow":
            raise ValueError("only Shadow attempts can be observed")
        if attempt.status not in {
            "denied",
            "shadow_valid",
            "shadow_invalid",
            "failed",
        }:
            raise ValueError(
                f"non-terminal Shadow status: {attempt.status}"
            )
        admission = attempt.admission
        evidence = attempt.shadow_evidence
        evaluation = attempt.shadow
        controller_fingerprint = (
            admission.controller_fingerprint
            if admission is not None
            else command.controller_fingerprint
        )
        if controller_fingerprint != command.controller_fingerprint:
            raise ValueError(
                "Shadow admission fingerprint differs from enrollment"
            )
        if (
            admission is not None
            and admission.source_commit_sha
            != command.source_commit_sha
        ):
            raise ValueError(
                "Shadow admission release differs from enrollment"
            )
        key = shadow_observation_key(
            command,
            controller_fingerprint,
        )
        error_values = list(
            evaluation.errors if evaluation is not None else ()
        )
        if attempt.reason:
            error_values.append(attempt.reason)
        return ShadowObservationAppend(
            observation_key=key,
            user_id=command.user_input.user_id,
            thread_id=command.user_input.thread_id,
            request_id=command.user_input.request_id,
            journal_sequence_watermark=(
                command.journal_sequence_watermark
            ),
            model_id=_uuid(command.user_input.model_uuid),
            certification_id=_uuid(
                admission.certification_id
                if admission is not None
                else None
            ),
            configuration_fingerprint=(
                admission.configuration_fingerprint
                if admission is not None
                else None
            ),
            source_commit_sha=command.source_commit_sha,
            controller_fingerprint=controller_fingerprint,
            agent_core_contract_version=AGENT_CORE_CONTRACT_VERSION,
            certification_contract_version=(
                AGENT_CERTIFICATION_CONTRACT_VERSION
            ),
            prompt_version=CONTROLLER_PROMPT_VERSION,
            context_snapshot_hash=(
                evidence.context_snapshot_hash
                if evidence is not None
                else None
            ),
            input_evidence_hash=(
                evidence.input_evidence_hash
                if evidence is not None
                else hash_shadow_text(command.user_input.content)
            ),
            controller_status=attempt.status,
            output_mode=(
                evidence.output_mode
                if evidence is not None
                else None
            ),
            valid=(
                evaluation.valid
                if evaluation is not None
                else None
            ),
            would_execute=bool(
                evaluation is not None
                and evaluation.would_execute
            ),
            side_effect_count=(
                evaluation.side_effect_count
                if evaluation is not None
                else 0
            ),
            latency_ms=max(0, latency_ms),
            proposal_summary=(
                evidence.proposal_summary
                if evidence is not None
                else {}
            ),
            plan_summary=_plan_summary(
                evaluation.plan
                if evaluation is not None
                else None
            ),
            checks=_safe_checks(
                evaluation.checks
                if evaluation is not None
                else []
            ),
            violation_codes=_violation_codes(
                evaluation,
                error_values,
            ),
            error_hashes=[
                hash_shadow_text(value)
                for value in error_values
            ],
        )


def _uuid(value: object) -> UUID | None:
    try:
        return UUID(str(value or ""))
    except (TypeError, ValueError):
        return None


def _plan_summary(plan) -> dict[str, Any]:
    if plan is None:
        return {}
    return {
        "source": plan.source,
        "route_type": plan.route_type,
        "intent": plan.intent,
        "response_mode": plan.response_mode,
        "complexity": plan.complexity,
        "actions": [
            {
                "capability": action.capability,
                "operation": action.operation,
                "required": action.required,
                "dependency_count": len(action.depends_on),
                "argument_hash": hash_shadow_json(
                    action.arguments
                ),
            }
            for action in plan.actions
        ],
    }


def _safe_checks(
    checks: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    allowed = {
        "capability",
        "status",
        "reason_codes",
        "step_count",
    }
    return [
        {
            key: value
            for key, value in check.items()
            if key in allowed
        }
        for check in checks
    ]


def _violation_codes(
    evaluation,
    errors: list[str],
) -> list[str]:
    codes: list[str] = []
    normalized_errors = [str(item).lower() for item in errors]
    if any(
        "system-owned field" in item
        for item in normalized_errors
    ):
        codes.append("system_owned_field")
    if any(
        "success claim" in item or "runtime receipt" in item
        for item in normalized_errors
    ):
        codes.append("unreceipted_success_claim")
    if evaluation is not None and any(
        isinstance(check, dict)
        and check.get("capability")
        in {"remember_memory", "forget_memory"}
        and check.get("status") != "ready"
        for check in evaluation.checks
    ):
        codes.append("memory_precommit_not_ready")
    return sorted(set(codes))


__all__ = ["ShadowObservationProjector"]
