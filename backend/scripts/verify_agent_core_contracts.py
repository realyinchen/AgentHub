"""Verify the first non-production Agent Core closed loop."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from uuid import uuid4


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.services.agent_core.contracts import (
    ControllerOutput,
    ControllerToolCall,
)
from app.services.agent_core.harness import AgentCoreHarness
from app.services.agent_runtime.contracts import ExecutionContext


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def _output() -> ControllerOutput:
    return ControllerOutput(
        mode="capability_proposals",
        tool_calls=[
            ControllerToolCall(
                call_id="latest-exchange",
                name="conversation_read",
                arguments={
                    "target": "exchange",
                    "selection": "latest",
                    "count": 1,
                },
            )
        ],
    )


def _context() -> ExecutionContext:
    return ExecutionContext(
        user_id=uuid4(),
        thread_id=uuid4(),
        request_id="verify-agent-core",
        metadata={
            "conversation_turns": [
                {
                    "role": "user",
                    "turn_offset": -2,
                    "content": "你好我是冰露",
                },
                {
                    "role": "assistant",
                    "turn_offset": -1,
                    "content": "你好，冰露！",
                },
            ]
        },
    )


async def _run() -> None:
    harness = AgentCoreHarness()
    shadow = await harness.run(
        _output(),
        goal="刚才我说什么了，你回复什么了？",
        context=_context(),
        execution_mode="shadow",
    )
    _assert(shadow.shadow is not None and shadow.shadow.valid, str(shadow))
    _assert(shadow.receipt is None, "shadow produced a receipt")
    _assert(shadow.shadow.side_effect_count == 0, str(shadow.shadow))
    _assert(shadow.plan is not None, "shadow did not compile a plan")
    _assert(shadow.plan.source == "shadow_validation", str(shadow.plan))

    live = await harness.run(
        _output(),
        goal="刚才我说什么了，你回复什么了？",
        context=_context(),
    )
    _assert(live.receipt is not None, "live run has no receipt")
    _assert(live.receipt.status == "completed", str(live.receipt))
    _assert(live.answer is not None and live.answer.receipt_backed, str(live))
    _assert("你好我是冰露" in live.answer.content, live.answer.content)
    _assert("你好，冰露" in live.answer.content, live.answer.content)
    _assert(
        live.plan is not None
        and live.plan.metadata.get("graph_normalized") is True,
        str(live.plan),
    )

    print("agent core minimal loop verification passed")
    print("shadow_side_effects=0")
    print("live_plan_source=controller_proposal")
    print("runtime_receipt=completed")
    print("publication=receipt_backed")


if __name__ == "__main__":
    asyncio.run(_run())
