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
    routing_funnel = _read("app/services/routing/funnel.py")
    routing_contracts = _read("app/services/routing/contracts.py")
    fast_path = _read("app/services/fast_path.py")

    for name, source in {
        "supervisor.py": supervisor,
        "context.py": context,
        "prompt.py": prompt_middleware,
        "chat.py": chat,
        "streaming.py": streaming,
        "routing/funnel.py": routing_funnel,
        "routing/contracts.py": routing_contracts,
        "fast_path.py": fast_path,
    }.items():
        ast.parse(source, filename=name)

    _assert("tools: list = []" in supervisor, "supervisor still registers tools")
    for name, source in (("chat", chat), ("streaming", streaming)):
        _assert(
            "LegacyChatRuntimeBridge" not in source
            and "prepare_runtime_turn" not in source,
            f"{name} still reaches the retired runtime",
        )
    _assert(
        "action_plan" in context and "plan_receipt" in context,
        "runtime context contract missing",
    )
    _assert(
        "build_turn_policy" not in prompt_middleware,
        "supervisor prompt still reclassifies raw user text",
    )
    _assert(
        "action_plan=action_plan" in prompt_middleware,
        "compiled ActionPlan is not projected into the final prompt",
    )
    _assert(
        "plan_receipt=plan_receipt" in prompt_middleware,
        "receipt is not projected into prompt",
    )
    _assert(
        "No direct tools are available" in prompt, "supervisor boundary prompt missing"
    )
    _assert("try_handle_fast_path" not in fast_path, "direct-answer fast path remains")
    _assert("RoutingDecision" in routing_contracts, "routing contract is missing")
    _assert(
        "services.agent_runtime.runtime" not in routing_funnel
        and ".execute(" not in routing_funnel,
        "routing bypasses ActionPlan",
    )
    _assert(
        "System Pre-Executed Tool Context" not in prompt, "old pre-tool context remains"
    )
    print("supervisor ActionPlan/runtime boundary verification passed")


if __name__ == "__main__":
    main()
