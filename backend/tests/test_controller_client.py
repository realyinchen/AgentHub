from __future__ import annotations

import sys
import unittest
from pathlib import Path

from langchain_core.messages import AIMessage, HumanMessage


BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services.agent_core.certification_contracts import AgentModeAdmission
from app.services.agent_core.capabilities import CapabilityRegistry
from app.services.agent_core.core_capabilities import (
    CoreCapabilityAvailability,
)
from app.services.agent_core.controller_client import (
    PLAN_TASK_TOOL,
    ControllerClient,
    ControllerClientError,
    _default_model_factory,
)
from app.services.agent_core.prompt_contracts import (
    ControllerContextSnapshot,
    ControllerModelRequest,
    ConversationContextTurn,
    TrustedMemoryContext,
    TrustedReceiptContext,
)


def _admission(*, admitted: bool = True) -> AgentModeAdmission:
    return AgentModeAdmission(
        admitted=admitted,
        certification_id="cert-1" if admitted else None,
        reason=None if admitted else "certification_missing",
        configuration_fingerprint="a" * 64,
        controller_fingerprint="b" * 64,
        source_commit_sha="c" * 40,
    )


def _request(*, admitted: bool = True) -> ControllerModelRequest:
    return ControllerModelRequest(
        model_name="test-controller",
        current_user_message="我刚才说了什么，你怎么回答的？",
        admission=_admission(admitted=admitted),
        context=ControllerContextSnapshot(
            conversation=[
                ConversationContextTurn(role="user", content="你好我是冰露"),
                ConversationContextTurn(
                    role="assistant",
                    content="你好，冰露！",
                ),
            ],
            memories=[
                TrustedMemoryContext(
                    schema_key="identity.self_reported_name",
                    fact="用户自述姓名为冰露",
                )
            ],
            receipts=[
                TrustedReceiptContext(
                    capability="remember_memory",
                    status="completed",
                    summary="姓名事实已创建",
                )
            ],
        ),
    )


def _enabled_registry() -> CapabilityRegistry:
    return CapabilityRegistry(
        core_availability=CoreCapabilityAvailability.all_enabled()
    )


class _BoundModel:
    def __init__(self, response: AIMessage) -> None:
        self.response = response
        self.schemas = None
        self.tool_choice = None
        self.messages = None

    def bind_tools(self, schemas, **kwargs):
        self.schemas = schemas
        self.tool_choice = kwargs.get("tool_choice")
        return self

    async def ainvoke(self, messages):
        self.messages = messages
        return self.response


class ControllerClientTests(unittest.IsolatedAsyncioTestCase):
    def test_default_factory_defers_thinking_mode_to_model_config(self) -> None:
        model = object()
        with unittest.mock.patch(
            "app.services.agent_core.controller_client.get_llm",
            return_value=model,
        ) as get_llm:
            result = _default_model_factory("configured-controller")

        self.assertIs(result, model)
        get_llm.assert_called_once_with("configured-controller")

    async def test_whole_conversation_is_sent_and_direct_answer_is_parsed(
        self,
    ) -> None:
        model = _BoundModel(AIMessage(content="你说你叫冰露，我向你问好。"))
        output = await ControllerClient(
            registry=_enabled_registry(),
            model_factory=lambda _name: model
        ).decide(_request())

        self.assertEqual(output.mode, "direct_answer")
        self.assertIn("冰露", output.text)
        human_messages = [
            message.content
            for message in model.messages
            if isinstance(message, HumanMessage)
        ]
        self.assertEqual(
            human_messages,
            ["你好我是冰露", "我刚才说了什么，你怎么回答的？"],
        )
        self.assertTrue(
            any("trusted_memory_facts" in str(message.content) for message in model.messages)
        )

    async def test_capability_schema_is_generated_without_system_identity(
        self,
    ) -> None:
        model = _BoundModel(
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "conversation_read",
                        "args": {
                            "target": "exchange",
                            "selection": "latest",
                            "count": 1,
                        },
                        "id": "call-read",
                        "type": "tool_call",
                    }
                ],
            )
        )
        output = await ControllerClient(
            registry=_enabled_registry(),
            model_factory=lambda _name: model
        ).decide(_request())

        self.assertEqual(output.mode, "capability_proposals")
        self.assertEqual(output.tool_calls[0].name, "conversation_read")
        serialized = str(model.schemas)
        for forbidden in ("user_id", "thread_id", "request_id", "memory_key"):
            self.assertNotIn(forbidden, serialized)
        self.assertEqual(model.tool_choice, "auto")

    async def test_clarification_is_control_signal_not_capability(self) -> None:
        model = _BoundModel(
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "request_clarification",
                        "args": {"question": "你希望我记住哪一个名字？"},
                        "id": "call-clarify",
                        "type": "tool_call",
                    }
                ],
            )
        )
        output = await ControllerClient(
            registry=_enabled_registry(),
            model_factory=lambda _name: model
        ).decide(_request())

        self.assertEqual(output.mode, "request_clarification")
        self.assertIn("哪一个名字", output.text)
        self.assertFalse(output.tool_calls)

    async def test_clarification_cannot_mix_with_business_capability(self) -> None:
        response = AIMessage(
            content="",
            tool_calls=[
                {
                    "name": "request_clarification",
                    "args": {"question": "请确认。"},
                    "id": "call-clarify",
                    "type": "tool_call",
                },
                {
                    "name": "search_memory",
                    "args": {"query": "name", "predicate": ""},
                    "id": "call-search",
                    "type": "tool_call",
                },
            ],
        )
        with self.assertRaisesRegex(
            ControllerClientError,
            "cannot be mixed",
        ):
            ControllerClient(
                registry=_enabled_registry(),
                model_factory=lambda _name: _BoundModel(response)
            ).parse(response)

    async def test_plan_task_is_typed_exclusive_control_signal(self) -> None:
        model = _BoundModel(
            AIMessage(
                content="我会先制定一个可恢复的两步任务。",
                tool_calls=[
                    {
                        "name": "plan_task",
                        "args": {
                            "goal": "查找并汇总最新图书",
                            "steps": [
                                {
                                    "step_key": "search",
                                    "title": "查找图书",
                                    "capability": "book_search",
                                    "arguments": {"query": "最新好评图书"},
                                },
                                {
                                    "step_key": "summarize",
                                    "title": "汇总结果",
                                    "capability": "research_start",
                                    "arguments": {"topic": "最新好评图书"},
                                    "depends_on": ["search"],
                                },
                            ],
                            "success_criteria": ["形成带来源的可读报告"],
                        },
                        "id": "call-task",
                        "type": "tool_call",
                    }
                ],
            )
        )
        output = await ControllerClient(
            registry=_enabled_registry(),
            model_factory=lambda _name: model
        ).decide(_request())

        self.assertEqual(output.mode, "task_plan_proposal")
        self.assertEqual(
            output.task_plan_proposal.goal,
            "查找并汇总最新图书",
        )
        self.assertEqual(len(output.task_plan_proposal.steps), 2)
        self.assertFalse(output.tool_calls)
        self.assertIn("制定", output.progress_text)
        self.assertEqual(
            PLAN_TASK_TOOL["function"]["parameters"]["title"],
            "TaskPlanDraft",
        )
        serialized = str(PLAN_TASK_TOOL)
        self.assertNotIn("create_task_plan", serialized)
        for forbidden in (
            "user_id",
            "thread_id",
            "origin_request_id",
            "task_id",
            "plan_version_id",
        ):
            self.assertNotIn(forbidden, serialized)

    async def test_plan_task_cannot_mix_with_business_capability(self) -> None:
        response = AIMessage(
            content="",
            tool_calls=[
                {
                    "name": "plan_task",
                    "args": {
                        "goal": "读取再检索",
                        "steps": [
                            {
                                "step_key": "read",
                                "title": "读对话",
                                "capability": "conversation_read",
                            }
                        ],
                    },
                    "id": "call-task",
                    "type": "tool_call",
                },
                {
                    "name": "conversation_read",
                    "args": {
                        "target": "exchange",
                        "selection": "latest",
                        "count": 1,
                    },
                    "id": "call-read",
                    "type": "tool_call",
                },
            ],
        )
        with self.assertRaisesRegex(
            ControllerClientError,
            "cannot be mixed",
        ):
            ControllerClient().parse(response)

    async def test_denied_admission_never_builds_or_calls_model(self) -> None:
        called = False

        def factory(_name):
            nonlocal called
            called = True
            return _BoundModel(AIMessage(content="should not run"))

        with self.assertRaisesRegex(
            ControllerClientError,
            "agent_mode_denied",
        ):
            await ControllerClient(model_factory=factory).decide(
                _request(admitted=False)
            )
        self.assertFalse(called)


if __name__ == "__main__":
    unittest.main()
