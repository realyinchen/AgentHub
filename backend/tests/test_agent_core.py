from __future__ import annotations

import unittest
from uuid import uuid4

from pydantic import ValidationError

from app.services.agent_core.capabilities import CapabilityRegistry
from app.services.agent_core.core_capabilities import (
    CoreCapabilityAvailability,
)
from app.services.agent_core.compiler import WorkflowCompiler
from app.services.agent_core.contracts import (
    ControllerOutput,
    ControllerToolCall,
)
from app.services.agent_core.harness import AgentCoreHarness
from app.services.agent_core.plan_graph import PlanGraphNormalizer
from app.services.agent_core.proposal_validator import ProposalValidator
from app.services.agent_core.prompt_composer import (
    CONTROLLER_PROMPT_VERSION,
    PromptComposer,
)
from app.services.agent_core.publisher import ResponsePublisher
from app.services.agent_runtime.contracts import (
    ActionPlan,
    ActionReceipt,
    ExecutionContext,
    PlanReceipt,
    PlannedAction,
)
from app.services.conversation import (
    ConversationReadRequest,
    ConversationTurn,
    ConversationWindow,
    read_conversation,
)
from app.services.tasks.contracts import TaskPlanDraft, TaskPlanStepDraft


def _context() -> ExecutionContext:
    return ExecutionContext(
        user_id=uuid4(),
        thread_id=uuid4(),
        request_id="agent-core-test",
        metadata={
            "conversation_turns": [
                {
                    "role": "user",
                    "turn_offset": -4,
                    "content": "你好我是冰露",
                },
                {
                    "role": "assistant",
                    "turn_offset": -3,
                    "content": "你好，冰露！",
                },
                {
                    "role": "user",
                    "turn_offset": -2,
                    "content": "记住我的名字",
                },
                {
                    "role": "assistant",
                    "turn_offset": -1,
                    "content": "我需要执行成功后才能确认。",
                },
            ]
        },
    )


def _enabled_registry() -> CapabilityRegistry:
    return CapabilityRegistry(
        core_availability=CoreCapabilityAvailability.all_enabled()
    )


def _conversation_output() -> ControllerOutput:
    return ControllerOutput(
        mode="capability_proposals",
        tool_calls=[
            ControllerToolCall(
                call_id="read-latest",
                name="conversation_read",
                arguments={
                    "target": "exchange",
                    "selection": "latest",
                    "count": 1,
                },
            )
        ],
    )


class ControllerContractTests(unittest.TestCase):
    def test_mode_schema_defines_clarification_boundary(self) -> None:
        description = ControllerOutput.model_json_schema()["properties"][
            "mode"
        ]["description"]

        self.assertIn("essential missing input", description)
        self.assertIn("terminal answer", description)

    def test_prompt_defines_clarification_and_receipt_boundaries(
        self,
    ) -> None:
        prompt = PromptComposer(_enabled_registry()).core_prompt()

        self.assertEqual(CONTROLLER_PROMPT_VERSION, "controller-prompt-v4")
        self.assertIn(
            "request_clarification is the only mode",
            prompt,
        )
        self.assertIn(
            "without a trusted receipt",
            prompt,
        )

    def test_direct_answer_and_tool_calls_are_mutually_exclusive(self) -> None:
        with self.assertRaises(ValidationError):
            ControllerOutput(
                mode="direct_answer",
                text="直接回答",
                tool_calls=[
                    ControllerToolCall(
                        call_id="read",
                        name="conversation_read",
                    )
                ],
            )

    def test_nested_system_field_is_rejected(self) -> None:
        output = ControllerOutput(
            mode="capability_proposals",
            tool_calls=[
                ControllerToolCall(
                    call_id="read",
                    name="conversation_read",
                    arguments={
                        "target": "exchange",
                        "selection": "latest",
                        "count": 1,
                        "metadata": {"thread_id": "forbidden"},
                    },
                )
            ],
        )
        with self.assertRaisesRegex(ValueError, "thread_id"):
            ProposalValidator().validate(output)

    def test_remember_contract_compiles_without_storage_identity(self) -> None:
        registry = _enabled_registry()
        self.assertIsNotNone(registry.get("remember_memory"))
        self.assertIn("remember_memory", registry.enabled_names)
        output = ControllerOutput(
            mode="capability_proposals",
            tool_calls=[
                ControllerToolCall(
                    call_id="remember",
                    name="remember_memory",
                    arguments={
                        "assertions": [
                            {
                                "subject": "user",
                                "predicate": "name",
                                "value": {"name": "冰露"},
                                "qualifiers": {},
                                "evidence_quote": "I am 冰露",
                            }
                        ]
                    },
                )
            ],
        )
        batch = ProposalValidator(registry).validate(output)
        plan = WorkflowCompiler().compile(batch, goal="I am 冰露")
        self.assertEqual(plan.actions[0].operation, "remember_memory_v2")
        self.assertNotIn("user_id", plan.actions[0].arguments)
        self.assertNotIn("memory_key", plan.actions[0].arguments)

    def test_task_plan_proposal_is_mutually_exclusive(self) -> None:
        draft = TaskPlanDraft(
            goal="读取历史",
            steps=[
                TaskPlanStepDraft(
                    step_key="read",
                    title="读取历史",
                    capability="conversation_read",
                )
            ],
        )
        with self.assertRaises(ValidationError):
            ControllerOutput(
                mode="task_plan_proposal",
                text="任务已经创建。",
                task_plan_proposal=draft,
            )
        with self.assertRaises(ValidationError):
            ControllerOutput(
                mode="task_plan_proposal",
                task_plan_proposal=draft,
                tool_calls=[
                    ControllerToolCall(
                        call_id="read",
                        name="conversation_read",
                    )
                ],
            )


class ConversationReadTests(unittest.TestCase):
    def test_exchange_read_pairs_user_and_assistant(self) -> None:
        window = ConversationWindow(
            turns=[
                ConversationTurn(
                    role="user",
                    turn_offset=-4,
                    content="第一问",
                ),
                ConversationTurn(
                    role="assistant",
                    turn_offset=-3,
                    content="第一答",
                ),
                ConversationTurn(
                    role="user",
                    turn_offset=-2,
                    content="第二问",
                ),
                ConversationTurn(
                    role="assistant",
                    turn_offset=-1,
                    content="第二答",
                ),
            ]
        )
        result = read_conversation(
            window,
            ConversationReadRequest(
                target="exchange",
                selection="last_n",
                count=2,
            ),
        )
        self.assertEqual(
            [
                (item.user.content, item.assistant.content)
                for item in result.exchanges
                if item.assistant is not None
            ],
            [("第一问", "第一答"), ("第二问", "第二答")],
        )

    def test_assistant_read_never_returns_user_turns(self) -> None:
        window = ConversationWindow(
            turns=[
                ConversationTurn(role="user", turn_offset=-2, content="问题"),
                ConversationTurn(
                    role="assistant",
                    turn_offset=-1,
                    content="回答",
                ),
            ]
        )
        result = read_conversation(
            window,
            ConversationReadRequest(target="assistant"),
        )
        self.assertEqual([item.role for item in result.turns], ["assistant"])
        self.assertIn("回答", result.answer)


class PlanGraphTests(unittest.TestCase):
    def test_plan_is_stably_topologically_sorted(self) -> None:
        first = PlannedAction(
            action_id="first",
            capability="test",
            operation="first",
        )
        second = PlannedAction(
            action_id="second",
            capability="test",
            operation="second",
            depends_on=["first"],
        )
        plan = ActionPlan(
            source="controller_proposal",
            route_type="fast_path",
            intent="test",
            goal="test",
            actions=[second, first],
        )
        normalized = PlanGraphNormalizer().normalize(plan)
        self.assertEqual(
            [item.action_id for item in normalized.actions],
            ["first", "second"],
        )

    def test_dependency_cycle_is_rejected(self) -> None:
        plan = ActionPlan(
            source="controller_proposal",
            route_type="fast_path",
            intent="test",
            goal="test",
            actions=[
                PlannedAction(
                    action_id="a",
                    capability="test",
                    operation="a",
                    depends_on=["b"],
                ),
                PlannedAction(
                    action_id="b",
                    capability="test",
                    operation="b",
                    depends_on=["a"],
                ),
            ],
        )
        with self.assertRaisesRegex(ValueError, "cycle"):
            PlanGraphNormalizer().normalize(plan)

    def test_action_plan_rejects_nested_system_fields(self) -> None:
        with self.assertRaises(ValidationError):
            PlannedAction(
                capability="test",
                operation="test",
                arguments={"nested": [{"credentials": "forbidden"}]},
            )


class AgentCoreHarnessTests(unittest.IsolatedAsyncioTestCase):
    async def test_live_fixture_closes_runtime_receipt_loop(self) -> None:
        class _ConversationRuntime:
            async def execute(self, plan, *, context, user_input=None):
                action = plan.actions[0]
                return PlanReceipt(
                    plan_id=plan.plan_id,
                    request_id=context.request_id,
                    route_type=plan.route_type,
                    intent=plan.intent,
                    status="completed",
                    actions=[
                        ActionReceipt(
                            action_id=action.action_id,
                            capability=action.capability,
                            operation=action.operation,
                            status="completed",
                            admitted=True,
                            output={
                                "result_mode": "conversation_read",
                                "status": "completed",
                                "answer": (
                                    "\u8bb0\u4f4f\u6211\u7684\u540d\u5b57\n"
                                    "\u6211\u9700\u8981\u6267\u884c\u6210\u529f"
                                    "\u540e\u624d\u80fd\u786e\u8ba4\u3002"
                                ),
                            },
                        )
                    ],
                )

        result = await AgentCoreHarness(
            registry=_enabled_registry(),
            runtime=_ConversationRuntime(),  # type: ignore[arg-type]
        ).run(
            _conversation_output(),
            goal="刚才我说什么了，你回复什么了？",
            context=_context(),
        )
        self.assertIsNotNone(result.plan)
        self.assertIsNotNone(result.receipt)
        self.assertIsNotNone(result.answer)
        self.assertEqual(result.receipt.status, "completed")
        self.assertTrue(result.answer.receipt_backed)
        self.assertIn("记住我的名字", result.answer.content)
        self.assertIn("我需要执行成功后才能确认", result.answer.content)

    async def test_shadow_runs_no_runtime_execution(self) -> None:
        class _ForbiddenRuntime:
            async def execute(self, *args, **kwargs):
                raise AssertionError("shadow mode executed runtime")

        result = await AgentCoreHarness(
            registry=_enabled_registry(),
            runtime=_ForbiddenRuntime(),  # type: ignore[arg-type]
        ).run(
            _conversation_output(),
            goal="shadow",
            context=_context(),
            execution_mode="shadow",
        )
        self.assertIsNone(result.receipt)
        self.assertTrue(result.shadow.valid)
        self.assertTrue(result.shadow.would_execute)
        self.assertEqual(result.shadow.side_effect_count, 0)

    async def test_memory_shadow_canonicalizes_without_side_effects(self) -> None:
        class _ForbiddenRuntime:
            calls = 0

            async def execute(self, *args, **kwargs):
                self.calls += 1
                raise AssertionError("shadow mode executed runtime")

        runtime = _ForbiddenRuntime()
        result = await AgentCoreHarness(
            registry=_enabled_registry(),
            runtime=runtime,  # type: ignore[arg-type]
        ).run(
            ControllerOutput(
                mode="capability_proposals",
                tool_calls=[
                    ControllerToolCall(
                        call_id="remember-name",
                        name="remember_memory",
                        arguments={
                            "assertions": [
                                {
                                    "subject": "self",
                                    "predicate": "name",
                                    "value": {"name": "冰露"},
                                    "qualifiers": {},
                                    "evidence_quote": "I am 冰露",
                                }
                            ]
                        },
                    )
                ],
            ),
            goal="I am 冰露",
            context=_context(),
            execution_mode="shadow",
        )
        self.assertEqual(runtime.calls, 0)
        self.assertIsNotNone(result.shadow)
        self.assertTrue(result.shadow.valid)
        self.assertEqual(result.shadow.side_effect_count, 1)
        self.assertEqual(result.shadow.checks[0]["status"], "ready")
        self.assertEqual(result.plan.source, "shadow_validation")

    async def test_direct_success_claim_without_receipt_is_rejected(self) -> None:
        output = ControllerOutput(
            mode="direct_answer",
            text="已经记录你的名字。",
        )
        with self.assertRaisesRegex(ValueError, "receipt"):
            await AgentCoreHarness(registry=_enabled_registry()).run(
                output,
                goal="remember",
                context=_context(),
            )

    async def test_shadow_rejects_direct_success_claim_without_receipt(
        self,
    ) -> None:
        output = ControllerOutput(
            mode="direct_answer",
            text="已经记录你的名字。",
        )

        result = await AgentCoreHarness(
            registry=_enabled_registry()
        ).run(
            output,
            goal="remember",
            context=_context(),
            execution_mode="shadow",
        )

        self.assertIsNotNone(result.shadow)
        self.assertFalse(result.shadow.valid)
        self.assertIn("receipt", result.shadow.errors[0])

    async def test_task_creation_is_compiled_and_published_from_receipt(
        self,
    ) -> None:
        class _TaskRuntime:
            async def execute(self, plan, *, context, user_input=None):
                action = plan.actions[0]
                return PlanReceipt(
                    plan_id=plan.plan_id,
                    request_id=context.request_id,
                    route_type=plan.route_type,
                    intent=plan.intent,
                    planner_used=plan.planner_used,
                    status="completed",
                    actions=[
                        ActionReceipt(
                            action_id=action.action_id,
                            capability=action.capability,
                            operation=action.operation,
                            status="completed",
                            admitted=True,
                            output={
                                "result_mode": "task_plan_mutation_receipt",
                                "status": "completed",
                                "mutation": "created",
                                "task_id": str(uuid4()),
                                "plan_version_id": str(uuid4()),
                                "version_no": 1,
                                "state_version": 1,
                                "step_count": 1,
                                "resume_required": False,
                            },
                        )
                    ],
                )

        result = await AgentCoreHarness(
            registry=_enabled_registry(),
            runtime=_TaskRuntime(),  # type: ignore[arg-type]
        ).run(
            ControllerOutput(
                mode="task_plan_proposal",
                task_plan_proposal=TaskPlanDraft(
                    goal="读取历史",
                    steps=[
                        TaskPlanStepDraft(
                            step_key="read",
                            title="读取历史",
                            capability="conversation_read",
                        )
                    ],
                ),
            ),
            goal="请创建一个读取历史的任务",
            context=_context(),
        )
        self.assertEqual(result.plan.actions[0].operation, "plan_task_v1")
        self.assertTrue(result.answer.receipt_backed)
        self.assertIn("已创建任务", result.answer.content)

    async def test_task_creation_shadow_never_calls_runtime(self) -> None:
        class _ForbiddenRuntime:
            async def execute(self, *args, **kwargs):
                raise AssertionError("shadow mode executed runtime")

        result = await AgentCoreHarness(
            registry=_enabled_registry(),
            runtime=_ForbiddenRuntime(),  # type: ignore[arg-type]
        ).run(
            ControllerOutput(
                mode="task_plan_proposal",
                task_plan_proposal=TaskPlanDraft(
                    goal="读取历史",
                    steps=[
                        TaskPlanStepDraft(
                            step_key="read",
                            title="读取历史",
                            capability="conversation_read",
                        )
                    ],
                ),
            ),
            goal="请创建一个读取历史的任务",
            context=_context(),
            execution_mode="shadow",
        )
        self.assertTrue(result.shadow.valid)
        self.assertTrue(result.shadow.would_execute)
        self.assertEqual(result.shadow.side_effect_count, 1)
        self.assertEqual(result.plan.source, "shadow_validation")

    async def test_model_response_mode_returns_intermediate_receipt(self) -> None:
        class _ModelCompiler:
            def compile(self, batch, *, goal):
                return ActionPlan(
                    source="controller_proposal",
                    route_type="slow_path",
                    intent="model_synthesis",
                    goal=goal,
                    response_mode="model",
                    actions=[
                        PlannedAction(
                            action_id="model-action",
                            capability="conversation",
                            operation="conversation_read",
                        )
                    ],
                )

        class _Runtime:
            async def execute(self, plan, *, context, user_input=None):
                action = plan.actions[0]
                return PlanReceipt(
                    plan_id=plan.plan_id,
                    request_id=context.request_id,
                    route_type=plan.route_type,
                    intent=plan.intent,
                    status="completed",
                    actions=[
                        ActionReceipt(
                            action_id=action.action_id,
                            capability=action.capability,
                            operation=action.operation,
                            status="completed",
                            output={"answer": "受信的中间结果"},
                            admitted=True,
                        )
                    ],
                )

        class _Publisher:
            def publish_receipt(self, *args, **kwargs):
                raise AssertionError(
                    "model response mode was published as a final answer"
                )

        result = await AgentCoreHarness(
            registry=_enabled_registry(),
            compiler=_ModelCompiler(),  # type: ignore[arg-type]
            runtime=_Runtime(),  # type: ignore[arg-type]
            publisher=_Publisher(),  # type: ignore[arg-type]
        ).run(
            _conversation_output(),
            goal="读取后综合",
            context=_context(),
        )

        self.assertIsNotNone(result.receipt)
        self.assertIsNone(result.answer)


class PublisherTests(unittest.TestCase):
    def test_clarification_requires_no_receipt(self) -> None:
        answer = ResponsePublisher().publish_direct(
            ControllerOutput(
                mode="request_clarification",
                text="你希望我记住的名字是什么？",
            )
        )
        self.assertEqual(answer.status, "clarification_required")
        self.assertFalse(answer.receipt_backed)

    def test_direct_task_created_claim_requires_receipt(self) -> None:
        with self.assertRaisesRegex(ValueError, "receipt"):
            ResponsePublisher().publish_direct(
                ControllerOutput(
                    mode="direct_answer",
                    text="任务已创建。",
                )
            )

    def test_waiting_receipt_publishes_clarification(self) -> None:
        plan = ActionPlan(
            source="controller_proposal",
            route_type="slow_path",
            intent="remember",
            goal="记住名字",
            response_mode="receipt",
            actions=[
                PlannedAction(
                    action_id="remember",
                    capability="memory",
                    operation="remember_memory_v2",
                )
            ],
        )
        answer = ResponsePublisher().publish_receipt(
            plan,
            PlanReceipt(
                plan_id=plan.plan_id,
                request_id="waiting",
                route_type=plan.route_type,
                intent=plan.intent,
                status="waiting",
                actions=[
                    ActionReceipt(
                        action_id="remember",
                        capability="memory",
                        operation="remember_memory_v2",
                        status="waiting",
                        admitted=True,
                        output={
                            "status": "clarification_required",
                            "clarification_question": "你的名字是什么？",
                        },
                    )
                ],
            ),
        )
        self.assertEqual(answer.status, "clarification_required")
        self.assertEqual(answer.content, "你的名字是什么？")


if __name__ == "__main__":
    unittest.main()
