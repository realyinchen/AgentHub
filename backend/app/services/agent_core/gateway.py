from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import model_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.infra.config import get_settings
from app.schemas.chat import UserInput
from app.services.agent_core.certification_contracts import AgentModeAdmission
from app.services.agent_core.contracts import (
    AgentCoreModel,
    ShadowEvaluationRecord,
    ShadowRunEvidence,
)
from app.services.agent_core.controller_client import ControllerClient
from app.services.agent_core.harness import AgentCoreHarness
from app.services.agent_core.request_builder import ControllerRequestBuilder
from app.services.agent_core.turn_contracts import TurnReceipt
from app.services.agent_core.turn_loop import TurnControllerLoop
from app.services.agent_core.shadow_evidence import (
    build_shadow_run_evidence,
)
from app.services.agent_runtime.contracts import ExecutionContext
from app.services.tasks.resume_dispatcher import TaskResumeDispatcher
from app.services.tasks.runner_contracts import TaskRunReceipt


AgentControllerMode = Literal["off", "shadow", "live"]
AgentControllerStatus = Literal[
    "off",
    "denied",
    "shadow_queued",
    "shadow_dropped",
    "shadow_valid",
    "shadow_invalid",
    "live_completed",
    "live_failed",
    "failed",
]


class AgentControllerAttempt(AgentCoreModel):
    mode: AgentControllerMode
    status: AgentControllerStatus
    admission: AgentModeAdmission | None = None
    shadow: ShadowEvaluationRecord | None = None
    shadow_evidence: ShadowRunEvidence | None = None
    turn: TurnReceipt | None = None
    task_run: TaskRunReceipt | None = None
    reason: str | None = None

    @model_validator(mode="after")
    def validate_projection(self) -> "AgentControllerAttempt":
        if self.status == "off":
            if self.mode != "off":
                raise ValueError("off status requires off mode")
        elif self.status == "denied":
            if self.admission is not None and self.admission.admitted:
                raise ValueError("denied attempt cannot be admitted")
            if not self.reason:
                raise ValueError("denied attempt requires a reason")
        elif self.status == "failed":
            if not self.reason:
                raise ValueError("failed attempt requires a reason")
        elif self.status == "shadow_queued":
            if self.mode != "shadow" or self.reason is not None:
                raise ValueError(
                    "queued Shadow attempt requires shadow mode and no reason"
                )
        elif self.status == "shadow_dropped":
            if self.mode != "shadow" or not self.reason:
                raise ValueError(
                    "dropped Shadow attempt requires a reason"
                )
        elif self.status.startswith("shadow_"):
            if self.mode != "shadow" or self.shadow is None:
                raise ValueError(
                    "shadow attempt requires a shadow evaluation"
                )
        elif self.mode != "live" or self.turn is None:
            raise ValueError("live attempt requires a TurnReceipt")
        return self


class AgentControllerGateway:
    """Feature-gated admission boundary for shadow and live Controller use."""

    def __init__(
        self,
        *,
        controller: ControllerClient | None = None,
        harness: AgentCoreHarness | None = None,
        request_builder: ControllerRequestBuilder | None = None,
        resume_dispatcher: TaskResumeDispatcher | None = None,
        admission_loader=None,
    ) -> None:
        self._controller = controller or ControllerClient()
        self._harness = harness or AgentCoreHarness()
        self._request_builder = (
            request_builder or ControllerRequestBuilder()
        )
        self._resume_dispatcher = (
            resume_dispatcher or TaskResumeDispatcher()
        )
        self._admission_loader = (
            admission_loader or _default_admission_loader
        )

    async def evaluate(
        self,
        db: AsyncSession,
        *,
        user_input: UserInput,
        model_name: str,
        mode: AgentControllerMode | None = None,
        journal_sequence_watermark: int | None = None,
        execution_request_id: str | None = None,
    ) -> AgentControllerAttempt:
        selected_mode = mode or get_settings().AGENT_CONTROLLER_V1_MODE
        if execution_request_id is not None:
            if selected_mode != "shadow":
                raise ValueError(
                    "execution_request_id override is Shadow-only"
                )
            if not execution_request_id.strip() or len(
                execution_request_id
            ) > 128:
                raise ValueError(
                    "invalid Shadow execution request id"
                )
        if selected_mode == "off":
            return AgentControllerAttempt(mode="off", status="off")

        try:
            model_id = UUID(str(user_input.model_uuid or ""))
        except (TypeError, ValueError):
            return AgentControllerAttempt(
                mode=selected_mode,
                status="denied",
                reason="certification_missing",
            )
        admission = await self._admission_loader(db, model_id)
        if not admission.admitted:
            return AgentControllerAttempt(
                mode=selected_mode,
                status="denied",
                admission=admission,
                reason=admission.reason or "certification_failed",
            )

        shadow_evidence = None
        try:
            request = await self._request_builder.build(
                db,
                user_input=user_input,
                model_name=model_name,
                admission=admission,
                journal_sequence_watermark=(
                    journal_sequence_watermark
                ),
            )
            context = ExecutionContext(
                user_id=user_input.user_id,
                thread_id=user_input.thread_id,
                request_id=(
                    execution_request_id
                    or user_input.request_id
                ),
                model_name=model_name,
                timezone=user_input.timezone,
            )
            if selected_mode == "shadow":
                output = await self._controller.decide(request)
                shadow_evidence = build_shadow_run_evidence(
                    request,
                    output,
                )
                result = await self._harness.run(
                    output,
                    goal=user_input.content,
                    context=context,
                    user_input=user_input,
                    execution_mode="shadow",
                )
                shadow = result.shadow
                if shadow is None:
                    raise RuntimeError(
                        "shadow harness returned no evaluation"
                    )
                return AgentControllerAttempt(
                    mode="shadow",
                    status=(
                        "shadow_valid"
                        if shadow.valid
                        else "shadow_invalid"
                    ),
                    admission=admission,
                    shadow=shadow,
                    shadow_evidence=shadow_evidence,
                )

            turn = await TurnControllerLoop(
                controller=self._controller,
                harness=self._harness,
            ).run(
                model_request=request,
                context=context,
                goal=user_input.content,
                user_input=user_input,
            )
            task_run = None
            for receipt in reversed(turn.plan_receipts):
                task_run = await self._resume_dispatcher.dispatch(
                    receipt,
                    context=context,
                )
                if task_run is not None:
                    break
            return AgentControllerAttempt(
                mode="live",
                status=(
                    "live_completed"
                    if turn.status
                    in {"completed", "clarification_required"}
                    else "live_failed"
                ),
                admission=admission,
                turn=turn,
                task_run=task_run,
            )
        except Exception as exc:
            return AgentControllerAttempt(
                mode=selected_mode,
                status="failed",
                admission=admission,
                shadow_evidence=shadow_evidence,
                reason=f"controller_unavailable:{exc.__class__.__name__}",
            )


async def _default_admission_loader(db: AsyncSession, model_id: UUID):
    from app.services.agent_certification import get_agent_mode_admission

    return await get_agent_mode_admission(
        db,
        model_id,
        source_commit_sha=get_settings().AGENT_RELEASE_COMMIT_SHA,
    )


__all__ = [
    "AgentControllerAttempt",
    "AgentControllerGateway",
    "AgentControllerMode",
    "AgentControllerStatus",
]
