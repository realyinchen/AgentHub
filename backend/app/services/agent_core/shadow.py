from __future__ import annotations

from app.services.agent_core.compiler import WorkflowCompiler
from app.services.agent_core.contracts import (
    ControllerOutput,
    ShadowEvaluationRecord,
)
from app.services.agent_core.plan_graph import PlanGraphNormalizer
from app.services.agent_core.proposal_validator import ProposalValidator
from app.services.agent_core.publisher import ResponsePublisher
from app.services.memory.canonicalizer import MemoryCanonicalizer
from app.services.memory.version_contracts import (
    ForgetMemoryRequest,
    RememberMemoryRequest,
)
from app.services.tasks.draft_validator import TaskPlanDraftValidator
from app.services.tasks.planning_compiler import TaskPlanningCompiler


class ShadowValidator:
    """Run the complete pre-execution path without invoking SystemRuntime."""

    def __init__(
        self,
        *,
        validator: ProposalValidator | None = None,
        compiler: WorkflowCompiler | None = None,
        task_planning_compiler: TaskPlanningCompiler | None = None,
        task_plan_validator: TaskPlanDraftValidator | None = None,
        normalizer: PlanGraphNormalizer | None = None,
    ) -> None:
        self._validator = validator or ProposalValidator()
        self._compiler = compiler or WorkflowCompiler()
        self._task_planning_compiler = (
            task_planning_compiler or TaskPlanningCompiler()
        )
        self._task_plan_validator = (
            task_plan_validator or TaskPlanDraftValidator()
        )
        self._normalizer = normalizer or PlanGraphNormalizer()

    def evaluate(
        self,
        output: ControllerOutput,
        *,
        goal: str,
    ) -> ShadowEvaluationRecord:
        if output.mode == "task_plan_proposal":
            try:
                if output.task_plan_proposal is None:
                    raise ValueError("typed task plan is required")
                validated = self._task_plan_validator.validate(
                    output.task_plan_proposal
                )
                plan = self._normalizer.normalize(
                    self._task_planning_compiler.compile(
                        validated,
                        goal=goal,
                        source="shadow_validation",
                    )
                )
            except Exception as exc:
                return ShadowEvaluationRecord(
                    valid=False,
                    errors=[str(exc) or exc.__class__.__name__],
                )
            return ShadowEvaluationRecord(
                valid=True,
                would_execute=True,
                side_effect_count=1 + len(
                    validated.side_effect_step_keys
                ),
                plan=plan,
                checks=[
                    {
                        "capability": "plan_task",
                        "status": "ready",
                        "step_count": len(output.task_plan_proposal.steps),
                    }
                ],
            )
        if output.mode != "capability_proposals":
            try:
                ResponsePublisher().publish_direct(output)
            except Exception as exc:
                return ShadowEvaluationRecord(
                    valid=False,
                    errors=[str(exc) or exc.__class__.__name__],
                )
            return ShadowEvaluationRecord(
                valid=True,
                would_execute=False,
            )
        try:
            batch = self._validator.validate(output)
            checks: list[dict] = []
            for proposal in batch.proposals:
                if proposal.capability == "remember_memory":
                    request = RememberMemoryRequest.model_validate(
                        proposal.arguments
                    )
                    canonical = MemoryCanonicalizer().canonicalize(
                        request.assertions,
                        source_text=goal,
                    )
                    checks.append(
                        {
                            "capability": proposal.capability,
                            "status": canonical.status,
                            "reason_codes": canonical.reason_codes,
                        }
                    )
                    if canonical.status != "ready":
                        return ShadowEvaluationRecord(
                            valid=False,
                            side_effect_count=0,
                            checks=checks,
                            errors=[
                                "memory canonicalization did not reach ready"
                            ],
                        )
                elif proposal.capability == "forget_memory":
                    request = ForgetMemoryRequest.model_validate(
                        proposal.arguments
                    )
                    targets = MemoryCanonicalizer().resolve_targets(
                        request.targets,
                        source_text=goal,
                    )
                    checks.append(
                        {
                            "capability": proposal.capability,
                            "status": targets.status,
                            "reason_codes": targets.reason_codes,
                        }
                    )
                    if targets.status != "ready":
                        return ShadowEvaluationRecord(
                            valid=False,
                            side_effect_count=0,
                            checks=checks,
                            errors=[
                                "memory target resolution did not reach ready"
                            ],
                        )
            plan = self._normalizer.normalize(
                self._compiler.compile(
                    batch,
                    goal=goal,
                    source="shadow_validation",
                )
            )
        except Exception as exc:
            return ShadowEvaluationRecord(
                valid=False,
                errors=[str(exc) or exc.__class__.__name__],
            )
        return ShadowEvaluationRecord(
            valid=True,
            would_execute=bool(plan.actions),
            side_effect_count=sum(
                1 for item in batch.proposals if item.side_effect
            ),
            plan=plan,
            checks=checks,
        )
