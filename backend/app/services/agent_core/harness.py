from __future__ import annotations

from app.schemas.chat import UserInput
from app.services.agent_core.capabilities import CapabilityRegistry
from app.services.agent_core.compiler import WorkflowCompiler
from app.services.agent_core.contracts import (
    AgentCoreTurnResult,
    ControllerOutput,
    ExecutionMode,
)
from app.services.agent_core.plan_graph import PlanGraphNormalizer
from app.services.agent_core.proposal_validator import ProposalValidator
from app.services.agent_core.publisher import ResponsePublisher
from app.services.agent_core.shadow import ShadowValidator
from app.services.agent_runtime.contracts import (
    ActionPlan,
    ExecutionContext,
    PlanReceipt,
)
from app.services.agent_runtime.runtime import SystemRuntime
from app.services.tasks.draft_validator import TaskPlanDraftValidator
from app.services.tasks.planning_compiler import TaskPlanningCompiler


class AgentCoreHarness:
    """Sequence the core loop; all domain work remains in collaborators."""

    def __init__(
        self,
        *,
        validator: ProposalValidator | None = None,
        compiler: WorkflowCompiler | None = None,
        task_planning_compiler: TaskPlanningCompiler | None = None,
        task_plan_validator: TaskPlanDraftValidator | None = None,
        normalizer: PlanGraphNormalizer | None = None,
        runtime: SystemRuntime | None = None,
        publisher: ResponsePublisher | None = None,
        registry: CapabilityRegistry | None = None,
    ) -> None:
        capability_registry = registry or CapabilityRegistry()
        self._validator = validator or ProposalValidator(
            capability_registry
        )
        self._compiler = compiler or WorkflowCompiler()
        self._task_planning_compiler = (
            task_planning_compiler or TaskPlanningCompiler()
        )
        self._task_plan_validator = (
            task_plan_validator
            or TaskPlanDraftValidator(capability_registry)
        )
        self._normalizer = normalizer or PlanGraphNormalizer()
        self._runtime = runtime or SystemRuntime(
            capability_registry=capability_registry
        )
        self._publisher = publisher or ResponsePublisher()

    async def run(
        self,
        output: ControllerOutput,
        *,
        goal: str,
        context: ExecutionContext,
        user_input: UserInput | None = None,
        execution_mode: ExecutionMode = "live",
    ) -> AgentCoreTurnResult:
        if execution_mode == "shadow":
            shadow = ShadowValidator(
                validator=self._validator,
                compiler=self._compiler,
                task_planning_compiler=self._task_planning_compiler,
                task_plan_validator=self._task_plan_validator,
                normalizer=self._normalizer,
            ).evaluate(output, goal=goal)
            return AgentCoreTurnResult(
                execution_mode="shadow",
                output=output,
                plan=shadow.plan,
                shadow=shadow,
            )

        if output.mode in {"direct_answer", "request_clarification"}:
            return AgentCoreTurnResult(
                execution_mode="live",
                output=output,
                answer=self._publisher.publish_direct(output),
            )

        if output.mode == "task_plan_proposal":
            if output.task_plan_proposal is None:
                raise ValueError("typed task plan is required")
            validated = self._task_plan_validator.validate(
                output.task_plan_proposal
            )
            plan = self._normalizer.normalize(
                self._task_planning_compiler.compile(
                    validated,
                    goal=goal,
                )
            )
        else:
            batch = self._validator.validate(output)
            plan = self._normalizer.normalize(
                self._compiler.compile(batch, goal=goal)
            )
        receipt = await self._runtime.execute(
            plan,
            context=context,
            user_input=user_input,
        )
        answer = (
            None
            if _requires_model_synthesis(plan, receipt)
            else self._publisher.publish_receipt(plan, receipt)
        )
        return AgentCoreTurnResult(
            execution_mode="live",
            output=output,
            plan=plan,
            receipt=receipt,
            answer=answer,
        )


def _requires_model_synthesis(
    plan: ActionPlan,
    receipt: PlanReceipt,
) -> bool:
    return (
        plan.response_mode == "model"
        and receipt.status in {"completed", "partial"}
        and any(action.status == "completed" for action in receipt.actions)
    )
