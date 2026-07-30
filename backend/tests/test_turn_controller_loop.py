from __future__ import annotations

import unittest
import uuid

from app.services.agent_core.capabilities import CapabilityRegistry
from app.services.agent_core.core_capabilities import (
    CoreCapabilityAvailability,
)
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
from app.services.agent_core.certification_contracts import AgentModeAdmission
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
        model_name="controller",
        current_user_message="继续完成任务",
        admission=AgentModeAdmission(
            admitted=True,
            certification_id="cert",
            configuration_fingerprint="a" * 64,
            controller_fingerprint="b" * 64,
            source_commit_sha="c" * 40,
        ),
        context=ControllerContextSnapshot(),
    )


def _enabled_registry() -> CapabilityRegistry:
    return CapabilityRegistry(
        core_availability=CoreCapabilityAvailability.all_enabled()
    )


def _context() -> ExecutionContext:
    return ExecutionContext(
        user_id=uuid.uuid4(),
        thread_id=uuid.uuid4(),
        request_id="turn-loop-request",
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


class _QueuedController:
    def __init__(self, outputs) -> None:
        self.outputs = list(outputs)
        self.requests = []

    async def decide(self, request):
        self.requests.append(request)
        return self.outputs.pop(0)


class _ModelRoundHarness:
    def __init__(self, *, raw_output: str = "SECRET_RAW_OUTPUT") -> None:
        self.calls = 0
        self.raw_output = raw_output

    async def run(self, output, *, goal, context, user_input=None):
        self.calls += 1
        if output.mode == "direct_answer":
            return await AgentCoreHarness(
                registry=_enabled_registry()
            ).run(
                output,
                goal=goal,
                context=context,
                user_input=user_input,
            )
        plan = ActionPlan(
            plan_id=f"model-plan-{self.calls}",
            source="controller_proposal",
            route_type="slow_path",
            intent="model_round",
            goal=goal,
            response_mode="model",
            actions=[
                PlannedAction(
                    action_id=f"model-action-{self.calls}",
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
                        output={"raw": self.raw_output},
                        admitted=True,
                    )
                ],
            ),
        )


class _TerminalRuntime:
    def __init__(self, status: str) -> None:
        self.status = status
        self.calls = 0

    async def execute(self, plan, *, context, user_input=None):
        self.calls += 1
        action = plan.actions[0]
        output = (
            {
                "status": "clarification_required",
                "clarification_question": "请补充信息。",
            }
            if self.status == "waiting"
            else None
        )
        return PlanReceipt(
            plan_id=plan.plan_id,
            request_id=context.request_id,
            route_type=plan.route_type,
            intent=plan.intent,
            status=self.status,
            actions=[
                ActionReceipt(
                    action_id=action.action_id,
                    capability=action.capability,
                    operation=action.operation,
                    status=self.status,
                    output=output,
                    admitted=True,
                )
            ],
        )


class TurnControllerLoopTests(unittest.IsolatedAsyncioTestCase):
    async def test_direct_answer_finishes_in_one_round(self) -> None:
        controller = _QueuedController(
            [ControllerOutput(mode="direct_answer", text="直接回答")]
        )
        receipt = await TurnControllerLoop(
            controller=controller,
            harness=AgentCoreHarness(registry=_enabled_registry()),
        ).run(
            model_request=_request(),
            context=_context(),
            goal="直接回答",
        )
        self.assertEqual(receipt.status, "completed")
        self.assertEqual(len(receipt.rounds), 1)
        self.assertEqual(receipt.final_answer.content, "直接回答")

    async def test_model_round_receipt_is_projected_without_raw_output(
        self,
    ) -> None:
        controller = _QueuedController(
            [
                _tool_output(),
                ControllerOutput(mode="direct_answer", text="综合完成"),
            ]
        )
        harness = _ModelRoundHarness()
        receipt = await TurnControllerLoop(
            controller=controller,
            harness=harness,
        ).run(
            model_request=_request(),
            context=_context(),
            goal="先读取再综合",
        )
        self.assertEqual(receipt.status, "completed")
        self.assertEqual(len(receipt.rounds), 2)
        self.assertEqual(
            receipt.final_answer.publication_mode,
            "model_synthesis",
        )
        self.assertTrue(receipt.final_answer.receipt_backed)
        self.assertEqual(
            receipt.final_answer.receipt_refs,
            ["model-action-1"],
        )
        self.assertEqual(len(controller.requests[1].context.receipts), 1)
        projected = controller.requests[1].context.receipts[0]
        self.assertNotIn(harness.raw_output, projected.summary)

    async def test_allowlisted_conversation_answer_is_projected(self) -> None:
        controller = _QueuedController(
            [
                _tool_output(),
                ControllerOutput(mode="direct_answer", text="综合完成"),
            ]
        )

        class _AnswerHarness(_ModelRoundHarness):
            async def run(
                self,
                output,
                *,
                goal,
                context,
                user_input=None,
            ):
                result = await super().run(
                    output,
                    goal=goal,
                    context=context,
                    user_input=user_input,
                )
                if result.receipt is None:
                    return result
                action = result.receipt.actions[0].model_copy(
                    update={"output": {"answer": "上一轮的可信回答"}}
                )
                return result.model_copy(
                    update={
                        "receipt": result.receipt.model_copy(
                            update={"actions": [action]}
                        )
                    }
                )

        receipt = await TurnControllerLoop(
            controller=controller,
            harness=_AnswerHarness(),
        ).run(
            model_request=_request(),
            context=_context(),
            goal="读取后综合",
        )
        self.assertEqual(receipt.status, "completed")
        self.assertIn(
            "上一轮的可信回答",
            controller.requests[1].context.receipts[0].summary,
        )

    async def test_waiting_receipt_stops_without_second_controller_call(
        self,
    ) -> None:
        controller = _QueuedController([_tool_output()])
        runtime = _TerminalRuntime("waiting")
        receipt = await TurnControllerLoop(
            controller=controller,
            harness=AgentCoreHarness(
                registry=_enabled_registry(),
                runtime=runtime,  # type: ignore[arg-type]
            ),
        ).run(
            model_request=_request(),
            context=_context(),
            goal="等待澄清",
        )
        self.assertEqual(receipt.status, "clarification_required")
        self.assertEqual(len(controller.requests), 1)
        self.assertEqual(runtime.calls, 1)

    async def test_failed_receipt_stops_without_second_controller_call(
        self,
    ) -> None:
        controller = _QueuedController([_tool_output()])
        runtime = _TerminalRuntime("failed")
        receipt = await TurnControllerLoop(
            controller=controller,
            harness=AgentCoreHarness(
                registry=_enabled_registry(),
                runtime=runtime,  # type: ignore[arg-type]
            ),
        ).run(
            model_request=_request(),
            context=_context(),
            goal="失败终止",
        )
        self.assertEqual(receipt.status, "failed")
        self.assertEqual(len(controller.requests), 1)
        self.assertEqual(runtime.calls, 1)

    async def test_round_limit_stops_without_seventh_call(self) -> None:
        controller = _QueuedController([_tool_output(), _tool_output()])
        harness = _ModelRoundHarness()
        receipt = await TurnControllerLoop(
            controller=controller,
            harness=harness,
            max_rounds=2,
        ).run(
            model_request=_request(),
            context=_context(),
            goal="循环",
        )
        self.assertEqual(receipt.status, "limit_exceeded")
        self.assertEqual(len(controller.requests), 2)
        self.assertEqual(harness.calls, 2)
        self.assertEqual(receipt.final_answer.status, "failed")


if __name__ == "__main__":
    unittest.main()
