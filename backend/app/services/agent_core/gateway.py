from __future__ import annotations

from typing import Literal

from pydantic import model_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.chat import UserInput
from app.services.agent_core.capabilities import CapabilityRegistry
from app.services.agent_core.contracts import (
    AgentCoreModel,
)
from app.services.agent_core.controller_client import ControllerClient
from app.services.agent_core.harness import AgentCoreHarness
from app.services.agent_core.request_builder import ControllerRequestBuilder
from app.services.agent_core.turn_contracts import TurnReceipt
from app.services.agent_core.turn_loop import TurnControllerLoop
from app.services.agent_runtime.contracts import ExecutionContext
from app.services.tasks.resume_dispatcher import TaskResumeDispatcher
from app.services.tasks.runner_contracts import TaskRunReceipt


AgentControllerMode = Literal["live"]
AgentControllerStatus = Literal[
    "live_completed",
    "live_failed",
    "failed",
]


class AgentControllerAttempt(AgentCoreModel):
    mode: AgentControllerMode
    status: AgentControllerStatus
    turn: TurnReceipt | None = None
    task_run: TaskRunReceipt | None = None
    reason: str | None = None

    @model_validator(mode="after")
    def validate_projection(self) -> "AgentControllerAttempt":
        if self.status == "failed":
            if not self.reason:
                raise ValueError("failed attempt requires a reason")
        elif self.turn is None:
            raise ValueError("live attempt requires a TurnReceipt")
        return self


class AgentControllerGateway:
    """The sole production boundary for Agent Core execution."""

    def __init__(
        self,
        *,
        controller: ControllerClient | None = None,
        harness: AgentCoreHarness | None = None,
        request_builder: ControllerRequestBuilder | None = None,
        resume_dispatcher: TaskResumeDispatcher | None = None,
        registry: CapabilityRegistry | None = None,
    ) -> None:
        capability_registry = registry or CapabilityRegistry()
        self._controller = controller or ControllerClient(
            registry=capability_registry
        )
        self._harness = harness or AgentCoreHarness(
            registry=capability_registry
        )
        self._request_builder = (
            request_builder or ControllerRequestBuilder()
        )
        self._resume_dispatcher = (
            resume_dispatcher or TaskResumeDispatcher()
        )

    async def evaluate(
        self,
        db: AsyncSession,
        *,
        user_input: UserInput,
        model_name: str,
        journal_sequence_watermark: int | None = None,
    ) -> AgentControllerAttempt:
        try:
            request = await self._request_builder.build(
                db,
                user_input=user_input,
                model_name=model_name,
                journal_sequence_watermark=journal_sequence_watermark,
            )
            context = ExecutionContext(
                user_id=user_input.user_id,
                thread_id=user_input.thread_id,
                request_id=user_input.request_id,
                model_name=model_name,
                timezone=user_input.timezone,
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
                turn=turn,
                task_run=task_run,
            )
        except Exception as exc:
            return AgentControllerAttempt(
                mode="live",
                status="failed",
                reason=f"controller_unavailable:{exc.__class__.__name__}",
            )

__all__ = [
    "AgentControllerAttempt",
    "AgentControllerGateway",
    "AgentControllerMode",
    "AgentControllerStatus",
]
