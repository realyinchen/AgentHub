from __future__ import annotations

from typing import Protocol

from app.schemas.chat import UserInput
from app.services.agent_core.contracts import (
    AgentCoreTurnResult,
    ControllerOutput,
    PublishedAnswer,
)
from app.services.agent_core.prompt_contracts import ControllerModelRequest
from app.services.agent_core.publication.contracts import (
    ReceiptEvidenceBundle,
)
from app.services.agent_core.publication.service import TrustedPublisher
from app.services.agent_core.receipt_projector import (
    ReceiptContextProjector,
)
from app.services.agent_core.turn_contracts import (
    ControllerRoundReceipt,
    TurnReceipt,
)
from app.services.agent_runtime.contracts import ExecutionContext


MAX_CONTROLLER_ROUNDS = 6


class ControllerPort(Protocol):
    async def decide(
        self,
        request: ControllerModelRequest,
    ) -> ControllerOutput: ...


class HarnessPort(Protocol):
    async def run(
        self,
        output: ControllerOutput,
        *,
        goal: str,
        context: ExecutionContext,
        user_input: UserInput | None = None,
    ) -> AgentCoreTurnResult: ...


class TurnControllerLoop:
    """Bound one Controller/ActionPlan/Receipt sequence to at most six rounds."""

    def __init__(
        self,
        *,
        controller: ControllerPort,
        harness: HarnessPort,
        projector: ReceiptContextProjector | None = None,
        publisher: TrustedPublisher | None = None,
        max_rounds: int = MAX_CONTROLLER_ROUNDS,
    ) -> None:
        value = int(max_rounds)
        if value < 1 or value > MAX_CONTROLLER_ROUNDS:
            raise ValueError("max_rounds must be between 1 and 6")
        self._controller = controller
        self._harness = harness
        self._projector = projector or ReceiptContextProjector()
        self._publisher = publisher or TrustedPublisher()
        self._max_rounds = value

    async def run(
        self,
        *,
        model_request: ControllerModelRequest,
        context: ExecutionContext,
        goal: str,
        user_input: UserInput | None = None,
    ) -> TurnReceipt:
        request = model_request
        rounds: list[ControllerRoundReceipt] = []
        plan_receipts = []
        evidence: list[ReceiptEvidenceBundle] = []

        for round_no in range(1, self._max_rounds + 1):
            try:
                output = await self._controller.decide(request)
            except Exception:
                return _failed_turn(
                    request_id=context.request_id,
                    rounds=rounds,
                    plan_receipts=plan_receipts,
                    content="本轮控制决策未能安全完成。",
                )
            try:
                result = await self._harness.run(
                    output,
                    goal=goal,
                    context=context,
                    user_input=user_input,
                )
            except Exception:
                rounds.append(
                    ControllerRoundReceipt(
                        round_no=round_no,
                        output=output,
                    )
                )
                return _failed_turn(
                    request_id=context.request_id,
                    rounds=rounds,
                    plan_receipts=plan_receipts,
                    content="本轮执行未能形成可信回执。",
                )

            if result.receipt is not None:
                plan_receipts.append(result.receipt)
                if result.plan is not None:
                    evidence.append(
                        ReceiptEvidenceBundle(
                            plan=result.plan,
                            receipt=result.receipt,
                        )
                    )

            answer = result.answer
            if (
                answer is not None
                and output.mode == "direct_answer"
                and evidence
            ):
                try:
                    answer = self._publisher.publish_synthesis(
                        output,
                        evidence=evidence,
                    )
                except Exception:
                    rounds.append(
                        ControllerRoundReceipt(
                            round_no=round_no,
                            output=result.output,
                            plan=result.plan,
                            receipt=result.receipt,
                        )
                    )
                    return _failed_turn(
                        request_id=context.request_id,
                        rounds=rounds,
                        plan_receipts=plan_receipts,
                        content=(
                            "本轮综合结果未通过可信发布校验，"
                            "因此没有发布未经验证的内容。"
                        ),
                    )

            round_receipt = ControllerRoundReceipt(
                round_no=round_no,
                output=result.output,
                plan=result.plan,
                receipt=result.receipt,
                answer=answer,
            )
            rounds.append(round_receipt)

            if answer is not None:
                return TurnReceipt(
                    status=_answer_status(answer),
                    request_id=context.request_id,
                    rounds=rounds,
                    plan_receipts=plan_receipts,
                    final_answer=answer,
                )
            if result.plan is None or result.receipt is None:
                return _failed_turn(
                    request_id=context.request_id,
                    rounds=rounds,
                    plan_receipts=plan_receipts,
                    content="本轮没有形成可继续处理的计划回执。",
                )
            if result.plan.response_mode != "model":
                return _failed_turn(
                    request_id=context.request_id,
                    rounds=rounds,
                    plan_receipts=plan_receipts,
                    content="本轮回执缺少确定性的发布结果。",
                )
            if (
                result.receipt.status not in {"completed", "partial"}
                or not any(
                    action.status == "completed"
                    for action in result.receipt.actions
                )
            ):
                return _failed_turn(
                    request_id=context.request_id,
                    rounds=rounds,
                    plan_receipts=plan_receipts,
                    content="本轮工具结果不足以继续安全综合。",
                )

            projected = self._projector.project(result.receipt)
            if not projected:
                return _failed_turn(
                    request_id=context.request_id,
                    rounds=rounds,
                    plan_receipts=plan_receipts,
                    content="本轮没有可供继续综合的受信结果。",
                )
            receipts = [*request.context.receipts, *projected][-32:]
            request = request.model_copy(
                update={
                    "context": request.context.model_copy(
                        update={"receipts": receipts}
                    )
                }
            )

        return TurnReceipt(
            status="limit_exceeded",
            request_id=context.request_id,
            rounds=rounds,
            plan_receipts=plan_receipts,
            final_answer=PublishedAnswer(
                status="failed",
                content="本轮已达到安全控制轮数上限，未继续执行。",
                receipt_backed=False,
            ),
        )


def _answer_status(answer: PublishedAnswer) -> str:
    if answer.status == "completed":
        return "completed"
    if answer.status == "clarification_required":
        return "clarification_required"
    return "failed"


def _failed_turn(
    *,
    request_id: str,
    rounds: list[ControllerRoundReceipt],
    plan_receipts: list,
    content: str,
) -> TurnReceipt:
    return TurnReceipt(
        status="failed",
        request_id=request_id,
        rounds=rounds,
        plan_receipts=plan_receipts,
        final_answer=PublishedAnswer(
            status="failed",
            content=content,
            receipt_backed=False,
        ),
    )


__all__ = [
    "MAX_CONTROLLER_ROUNDS",
    "TurnControllerLoop",
]
