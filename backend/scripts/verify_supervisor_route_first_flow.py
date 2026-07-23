"""Verify the planner/runtime/supervisor boundary without external services."""

from __future__ import annotations

import ast
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]


def _read(relative: str) -> str:
    return (BACKEND_DIR / relative).read_text(encoding="utf-8")


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def main() -> None:
    supervisor = _read("app/agents/supervisor.py")
    context = _read("app/agents/context.py")
    prompt_middleware = _read("app/agents/middleware/prompt.py")
    prompt = _read("app/agents/prompts/supervisor.md")
    chat = _read("app/services/chat.py")
    streaming = _read("app/services/streaming.py")
    turn_execution = _read("app/services/turn_execution.py")
    fast_path = _read("app/services/fast_path.py")

    for name, source in {
        "supervisor.py": supervisor,
        "context.py": context,
        "prompt.py": prompt_middleware,
        "chat.py": chat,
        "streaming.py": streaming,
        "turn_execution.py": turn_execution,
        "fast_path.py": fast_path,
    }.items():
        ast.parse(source, filename=name)

    _assert("tools: list = []" in supervisor, "supervisor still registers tools")
    _assert("prepare_runtime_turn" in chat, "chat does not use unified runtime")
    _assert("prepare_runtime_turn" in streaming, "streaming does not use unified runtime")
    _assert("action_plan" in context and "plan_receipt" in context, "runtime context contract missing")
    _assert("plan_receipt=plan_receipt" in prompt_middleware, "receipt is not projected into prompt")
    _assert("No direct tools are available" in prompt, "supervisor boundary prompt missing")
    _assert("try_handle_fast_path" not in fast_path, "direct-answer fast path remains")
    _assert("execute_required_actions" not in turn_execution, "old pre-executor remains")
    _assert("System Pre-Executed Tool Context" not in prompt, "old pre-tool context remains")
    print("supervisor ActionPlan/runtime boundary verification passed")


if __name__ == "__main__":
    main()
