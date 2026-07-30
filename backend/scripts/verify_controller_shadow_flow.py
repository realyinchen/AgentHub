"""Verify certified Controller output enters shadow without execution."""

from __future__ import annotations

import asyncio
import sys
import uuid
from pathlib import Path

from langchain_core.messages import AIMessage


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.services.agent_core.certification_contracts import (
    AgentModeAdmission,
)
from app.services.agent_core.controller_client import ControllerClient
from app.services.agent_core.harness import AgentCoreHarness
from app.services.agent_core.prompt_contracts import (
    ControllerContextSnapshot,
    ControllerModelRequest,
    ConversationContextTurn,
)
from app.services.agent_runtime.contracts import ExecutionContext


class _ShadowModel:
    def __init__(self) -> None:
        self.schemas = None
        self.messages = None

    def bind_tools(self, schemas, **_kwargs):
        self.schemas = schemas
        return self

    async def ainvoke(self, messages):
        self.messages = messages
        return AIMessage(
            content="正在读取已发布的上一轮对话。",
            tool_calls=[
                {
                    "name": "conversation_read",
                    "args": {
                        "target": "exchange",
                        "selection": "latest",
                        "count": 1,
                    },
                    "id": "shadow-read-1",
                    "type": "tool_call",
                }
            ],
        )


async def _run() -> None:
    model = _ShadowModel()
    request = ControllerModelRequest(
        model_name="fixture-controller",
        current_user_message="刚才我说什么了，你回复什么了？",
        admission=AgentModeAdmission(
            admitted=True,
            certification_id="fixture-certification",
            configuration_fingerprint="a" * 64,
            controller_fingerprint="b" * 64,
            source_commit_sha="c" * 40,
        ),
        context=ControllerContextSnapshot(
            conversation=[
                ConversationContextTurn(role="user", content="你好我是冰露"),
                ConversationContextTurn(
                    role="assistant",
                    content="你好，冰露！",
                ),
            ]
        ),
    )
    output = await ControllerClient(
        model_factory=lambda _name: model
    ).decide(request)
    result = await AgentCoreHarness().run(
        output,
        goal=request.current_user_message,
        context=ExecutionContext(
            user_id=uuid.uuid4(),
            thread_id=uuid.uuid4(),
            request_id="controller-shadow-verifier",
        ),
        execution_mode="shadow",
    )

    if result.shadow is None or not result.shadow.valid:
        raise AssertionError("Controller proposal did not pass shadow validation")
    if result.shadow.side_effect_count != 0:
        raise AssertionError("shadow Controller path reported side effects")
    if result.receipt is not None:
        raise AssertionError("shadow Controller path produced a runtime receipt")
    if result.plan is None or result.plan.source != "shadow_validation":
        raise AssertionError("shadow plan source was not isolated")
    serialized = str(model.schemas)
    if "plan_task" not in serialized:
        raise AssertionError("model-visible schema omitted plan_task")
    if "create_task_plan" in serialized:
        raise AssertionError("legacy create_task_plan is still model-visible")
    for forbidden in ("user_id", "thread_id", "request_id", "memory_key"):
        if forbidden in serialized:
            raise AssertionError(
                f"model-visible schema exposed system field: {forbidden}"
            )

    print("controller shadow verification passed")
    print("whole_conversation=true")
    print("model_system_fields=0")
    print("runtime_executions=0")
    print("shadow_side_effects=0")


if __name__ == "__main__":
    asyncio.run(_run())
