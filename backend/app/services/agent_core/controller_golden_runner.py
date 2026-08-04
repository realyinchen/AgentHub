from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from app.services.agent_core.certification_contracts import (
    AgentModeAdmission,
)
from app.services.agent_core.capabilities import CapabilityRegistry
from app.services.agent_core.controller_client import ControllerClient
from app.services.agent_core.controller_golden_contracts import (
    ControllerGoldenCaseResult,
    ControllerGoldenReport,
    LoadedControllerGoldenDataset,
)
from app.services.agent_core.controller_golden_evaluator import (
    ControllerGoldenCaseEvaluator,
    ControllerGoldenReportEvaluator,
)
from app.services.agent_core.evidence_source import GitSourceState
from app.services.agent_core.core_capabilities import (
    CoreCapabilityAvailability,
)
from app.services.agent_core.proposal_validator import ProposalValidator
from app.services.agent_core.prompt_contracts import (
    ControllerModelRequest,
)
from app.services.agent_core.shadow import ShadowValidator
from app.services.tasks.draft_validator import TaskPlanDraftValidator


def golden_capability_registry() -> CapabilityRegistry:
    """Return the explicit non-production capability set for Golden runs.

    Golden evaluates the candidate Controller contract. It must not inherit
    production rollout flags, which intentionally remain disabled until the
    release gates pass.
    """

    return CapabilityRegistry(
        core_availability=CoreCapabilityAvailability.all_enabled()
    )


def golden_case_evaluator() -> ControllerGoldenCaseEvaluator:
    registry = golden_capability_registry()
    return ControllerGoldenCaseEvaluator(
        shadow_validator=ShadowValidator(
            validator=ProposalValidator(registry),
            task_plan_validator=TaskPlanDraftValidator(registry),
        )
    )


class ControllerGoldenRunner:
    """Call the Controller exactly once per synthetic case; never execute."""

    def __init__(
        self,
        *,
        controller: ControllerClient | None = None,
        case_evaluator: ControllerGoldenCaseEvaluator | None = None,
        report_evaluator: ControllerGoldenReportEvaluator | None = None,
    ) -> None:
        if controller is None:
            registry = golden_capability_registry()
            self._controller = ControllerClient(registry=registry)
        else:
            self._controller = controller
        self._cases = case_evaluator or golden_case_evaluator()
        self._reports = (
            report_evaluator or ControllerGoldenReportEvaluator()
        )

    async def run(
        self,
        loaded: LoadedControllerGoldenDataset,
        *,
        model_name: str,
        model_id: UUID,
        admission: AgentModeAdmission,
        source_state: GitSourceState,
        prompt_version: str,
        generated_at: datetime | None = None,
    ) -> ControllerGoldenReport:
        if not admission.admitted:
            raise ValueError(
                "Controller golden run requires successful admission"
            )
        if source_state.dirty_worktree:
            raise ValueError(
                "Controller golden run requires clean source"
            )
        if admission.source_commit_sha != source_state.commit_sha:
            raise ValueError(
                "Controller golden admission belongs to another release"
            )
        results: list[ControllerGoldenCaseResult] = []
        for case in loaded.dataset.cases:
            try:
                output = await self._controller.decide(
                    ControllerModelRequest(
                        model_name=model_name,
                        current_user_message=(
                            case.current_user_message
                        ),
                        context=case.context,
                        admission=admission,
                    )
                )
                result = self._cases.evaluate(
                    case,
                    output,
                    controller_call_count=1,
                )
            except Exception as exc:
                result = ControllerGoldenCaseResult(
                    case_id=case.case_id,
                    category=case.category,
                    passed=False,
                    required_capabilities_satisfied=False,
                    controller_call_count=1,
                    runtime_call_count=0,
                    reason_codes=[
                        "controller_error."
                        + exc.__class__.__name__.lower()
                    ],
                )
            results.append(result)
        return self._reports.evaluate(
            loaded.dataset,
            results,
            live_model_evidence=True,
            commit_sha=source_state.commit_sha,
            source_dirty_worktree=source_state.dirty_worktree,
            generated_at=generated_at or datetime.now(timezone.utc),
            model_id=model_id,
            certification_id=admission.certification_id,
            configuration_fingerprint=(
                admission.configuration_fingerprint
            ),
            controller_fingerprint=(
                admission.controller_fingerprint
            ),
            prompt_version=prompt_version,
            dataset_hash=loaded.sha256,
        )


__all__ = [
    "ControllerGoldenRunner",
    "golden_capability_registry",
    "golden_case_evaluator",
]
