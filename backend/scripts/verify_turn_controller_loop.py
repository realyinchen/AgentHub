"""Verify bounded Controller rounds and receipt-context isolation."""

from __future__ import annotations

import asyncio
import sys
import uuid
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.services.agent_core.certification_contracts import AgentModeAdmission
from app.services.agent_core.contracts import (
    AgentCoreTurnResult,
    ControllerOutput,
    ControllerToolCall,
)
from app.services.agent_core.harness import AgentCoreHarness
from app.services.agent_core.prompt_contracts import (
    ControllerContextSnapshot,
    ControllerModelRequest,
)
from app.services.agent_core.turn_loop import TurnControllerLoop
from app.services.agent_runtime.contracts import (
    ActionPlan,
    ActionReceipt,
    ExecutionContext,
    PlanReceipt,
    PlannedAction,
)


def _request() -> ControllerModelRequest:
    return ControllerModelRequest(
        model_name="controller-fixture",
        current_user_message="读取后回答",
        admission=AgentModeAdmission(
            admitted=True,
            certification_id="fixture",
            configuration_fingerprint="a" * 64,
            controller_fingerprint="b" * 64,
            source_commit_sha="c" * 40,
        ),
        context=ControllerContextSnapshot(),
    )


def _context() -> ExecutionContext:
    return ExecutionContext(
        user_id=uuid.uuid4(),
        thread_id=uuid.uuid4(),
        request_id="turn-loop-verifier",
    )


def _tool_output() -> ControllerOutput:
    return ControllerOutput(
        mode="capability_proposals",
        tool_calls=[
            ControllerToolCall(
                call_id="read",
                name="conversation_read",
                arguments={
                    "target": "exchange",
                    "selection": "latest",
                    "count": 1,
                },
            )
        ],
    )


class _Controller:
    def __init__(self, outputs) -> None:
        self.outputs = list(outputs)
        self.requests = []

    async def decide(self, request):
        self.requests.append(request)
        return self.outputs.pop(0)


class _ModelHarness:
    def __init__(self) -> None:
        self.calls = 0

    async def run(self, output, *, goal, context, user_input=None):
        self.calls += 1
        if output.mode == "direct_answer":
            return await AgentCoreHarness().run(
                output,
                goal=goal,
                context=context,
                user_input=user_input,
            )
        plan = ActionPlan(
            plan_id=f"loop-plan-{self.calls}",
            source="controller_proposal",
            route_type="slow_path",
            intent="fixture",
            goal=goal,
            response_mode="model",
            actions=[
                PlannedAction(
                    action_id=f"loop-action-{self.calls}",
                    capability="conversation",
                    operation="conversation_read",
                )
            ],
        )
        return AgentCoreTurnResult(
            execution_mode="live",
            output=output,
            plan=plan,
            receipt=PlanReceipt(
                plan_id=plan.plan_id,
                request_id=context.request_id,
                route_type=plan.route_type,
                intent=plan.intent,
                status="completed",
                actions=[
                    ActionReceipt(
                        action_id=plan.actions[0].action_id,
                        capability="conversation",
                        operation="conversation_read",
                        status="completed",
                        output={
                            "answer": "可投影答案",
                            "raw": "SECRET_RAW_PROVIDER_OUTPUT",
                        },
                        admitted=True,
                    )
                ],
            ),
        )


async def _run() -> None:
    direct_controller = _Controller(
        [ControllerOutput(mode="direct_answer", text="直接回答")]
    )
    direct = await TurnControllerLoop(
        controller=direct_controller,
        harness=AgentCoreHarness(),
    ).run(
        model_request=_request(),
        context=_context(),
        goal="直接回答",
    )
    if direct.status != "completed" or len(direct.rounds) != 1:
        raise AssertionError("direct Controller round did not terminate")

    controller = _Controller(
        [_tool_output(), ControllerOutput(mode="direct_answer", text="综合完成")]
    )
    harness = _ModelHarness()
    synthesized = await TurnControllerLoop(
        controller=controller,
        harness=harness,
    ).run(
        model_request=_request(),
        context=_context(),
        goal="读取后综合",
    )
    if synthesized.status != "completed" or len(synthesized.rounds) != 2:
        raise AssertionError("model synthesis did not complete in two rounds")
    projected = controller.requests[1].context.receipts[0].summary
    if "可投影答案" not in projected:
        raise AssertionError("allowlisted answer was not projected")
    if "SECRET_RAW_PROVIDER_OUTPUT" in projected:
        raise AssertionError("raw Provider output crossed the trust boundary")

    limited_controller = _Controller([_tool_output(), _tool_output()])
    limited_harness = _ModelHarness()
    limited = await TurnControllerLoop(
        controller=limited_controller,
        harness=limited_harness,
        max_rounds=2,
    ).run(
        model_request=_request(),
        context=_context(),
        goal="循环",
    )
    if limited.status != "limit_exceeded":
        raise AssertionError("bounded loop did not stop at its limit")
    if len(limited_controller.requests) != 2 or limited_harness.calls != 2:
        raise AssertionError("bounded loop executed beyond its limit")

    print("turn controller loop verification passed")
    print("direct_rounds=1")
    print("model_synthesis_rounds=2")
    print("raw_provider_output_leaks=0")
    print("limit_exceeded_rounds=2")
    print("post_limit_controller_calls=0")
    print("post_limit_tool_calls=0")


if __name__ == "__main__":
    asyncio.run(_run())
