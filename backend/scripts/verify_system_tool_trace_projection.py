"""Verify app-pre-executed tools are present in persisted DAG projections."""

from __future__ import annotations

import sys
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.schemas.trace import AIStepMetadata, DagNode, ExecutionDag, StepOutput
from app.utils.dag import inject_system_tool_steps


def _node(node_id: str, step_number: int, message_type: str) -> DagNode:
    return DagNode(
        node_id=node_id,
        step_number=step_number,
        node_name="user" if message_type == "human" else "model",
        title="User Input" if message_type == "human" else "AI Response",
        message_type=message_type,
        step=StepOutput(
            step_number=step_number,
            message_type=message_type,
            content="question" if message_type == "human" else "answer",
            node_name="__start__" if message_type == "human" else "model",
            ai_metadata=AIStepMetadata() if message_type == "ai" else None,
        ),
    )


def main() -> None:
    human = _node("human_1", 1, "human")
    ai = _node("ai_2", 2, "ai")
    dag = ExecutionDag(
        thread_id="trace-test",
        nodes=[human, ai],
        edges=[("human_1", "ai_2")],
        total_steps=2,
        steps=[human.step, ai.step],
    )

    projected = inject_system_tool_steps(
        dag,
        [
            {
                "action_id": "memory-lookup-1",
                "tool_name": "search_memory",
                "args": {"query": "介绍一下我自己"},
                "output": {"status": "ok", "result_count": 4},
                "status": "ok",
                "duration_ms": 23,
            }
        ],
    )

    assert [step.message_type for step in projected.steps] == ["human", "tool", "ai"]
    tool = projected.steps[1]
    assert tool.tool_name == "search_memory"
    assert tool.system_executed is True
    assert tool.latency_ms == 23
    assert projected.edges == [
        ("human_1", "system_tool_1_memory-lookup-1"),
        ("system_tool_1_memory-lookup-1", "ai_2"),
    ]
    print("system tool trace projection verification passed")


if __name__ == "__main__":
    main()
