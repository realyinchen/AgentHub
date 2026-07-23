r"""Verify the ActionPlan -> SystemRuntime -> PlanReceipt architecture.

This check intentionally avoids live web, research, and LLM provider calls. It
verifies deterministic planning, runtime-owned context injection, durable raw
user-state capture, cross-conversation recall, visible memory receipts, and
on-demand planner selection.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import uuid
from pathlib import Path

from dotenv import load_dotenv
from pydantic import ValidationError
from sqlalchemy import text


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.infra.database import dispose_database, get_database, init_database
from app.infra.llm.embedding import init_embedding_model
from app.schemas.chat import UserInput
from app.services.agent_runtime.contracts import PlannedAction
from app.services.agent_runtime.coordinator import prepare_runtime_turn
from app.services.agent_runtime.finalizer import (
    finalize_deterministic_receipt,
    receipt_trace_steps,
)
from app.services.agent_runtime.planner import ActionPlanner, build_fast_action_plan
from app.services.context_pack import ContextBuilder
from app.services.fast_path import decide_fast_path
from scripts.init_database import _init_postgres


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def _input(content: str, user_id: uuid.UUID, thread_id: uuid.UUID) -> UserInput:
    return UserInput(
        content=content,
        user_id=user_id,
        thread_id=thread_id,
        request_id=str(uuid.uuid4()),
        timezone="Asia/Shanghai",
    )


async def _insert_user_and_threads(
    user_id: uuid.UUID,
    thread_ids: list[uuid.UUID],
) -> None:
    db = get_database()
    async with db.session() as session:
        await session.execute(
            text(
                """
                INSERT INTO public.users (id, display_name, is_mock_user)
                VALUES (:user_id, :display_name, true)
                ON CONFLICT (id) DO NOTHING
                """
            ),
            {"user_id": user_id, "display_name": "Action Runtime Verify"},
        )
        for thread_id in thread_ids:
            await session.execute(
                text(
                    """
                    INSERT INTO public.conversations (thread_id, user_id, title)
                    VALUES (:thread_id, :user_id, :title)
                    ON CONFLICT (thread_id) DO NOTHING
                    """
                ),
                {
                    "thread_id": thread_id,
                    "user_id": user_id,
                    "title": "Action Runtime Verify",
                },
            )


async def _delete_user(user_id: uuid.UUID) -> None:
    db = get_database()
    async with db.session() as session:
        await session.execute(
            text("DELETE FROM public.users WHERE id = :user_id"),
            {"user_id": user_id},
        )


class _OfflinePlanner(ActionPlanner):
    async def _llm_plan(self, **_: object):
        return None, {"status": "offline_verification"}


def _verify_contract_boundary() -> None:
    try:
        PlannedAction(
            capability="memory",
            operation="search_memory",
            arguments={"query": "name", "user_id": str(uuid.uuid4())},
        )
    except ValidationError:
        pass
    else:
        raise AssertionError("ActionPlan accepted a system-owned user_id")

    import app.services.fast_path as fast_path
    import app.services.turn_execution as turn_execution

    _assert(
        not hasattr(fast_path, "try_handle_fast_path"),
        "legacy direct-answer fast path still exists",
    )
    _assert(
        not hasattr(turn_execution, "prepare_turn_execution_context"),
        "legacy pre-execution entry still exists",
    )
    prompt = (
        BACKEND_DIR / "app" / "agents" / "prompts" / "supervisor.md"
    ).read_text(encoding="utf-8")
    _assert("No direct tools are available" in prompt, "supervisor boundary missing")
    _assert("System Pre-Executed Tool Context" not in prompt, "old pre-tool prompt remains")


async def _verify_planning_without_live_calls(
    user_id: uuid.UUID,
    thread_id: uuid.UUID,
) -> None:
    weather = await ActionPlanner().plan(
        _input("\u4eca\u5929\u5929\u6c14\u600e\u4e48\u6837\uff1f", user_id, thread_id)
    )
    operations = [item.operation for item in weather.actions]
    _assert("web_search" in operations, str(weather))
    _assert("search_books" not in operations, str(weather))
    _assert(not weather.planner_used, "weather should use deterministic planning")

    address = await ActionPlanner().plan(
        _input("\u6cd5\u56fd\u5df4\u9ece\u5177\u4f53\u5730\u5740\u662f\u4ec0\u4e48?", user_id, thread_id)
    )
    _assert(
        [item.operation for item in address.actions] == ["web_search"],
        str(address),
    )

    mutable_role = await ActionPlanner().plan(
        _input("\u6cd5\u56fd\u603b\u7edf\u662f\u8c01\uff1f", user_id, thread_id)
    )
    _assert(
        [item.operation for item in mutable_role.actions] == ["web_search"],
        str(mutable_role),
    )
    _assert(not mutable_role.planner_used, str(mutable_role))

    uncertain_fact = await _OfflinePlanner().plan(
        _input("\u300a\u4e09\u4f53\u300b\u7684\u4f5c\u8005\u662f\u8c01\uff1f", user_id, thread_id)
    )
    _assert(uncertain_fact.planner_used, str(uncertain_fact))
    _assert(
        [item.operation for item in uncertain_fact.actions] == ["web_search"],
        str(uncertain_fact),
    )

    stable_explanation = await ActionPlanner().plan(
        _input("\u4ec0\u4e48\u662f\u9012\u5f52\uff1f", user_id, thread_id)
    )
    _assert(not stable_explanation.planner_used, str(stable_explanation))
    _assert(not stable_explanation.actions, str(stable_explanation))

    ambiguous_memory = await _OfflinePlanner().plan(
        _input("\u6211\u4ec0\u4e48\u65f6\u5019\u4ea4\u623f\u79df\uff1f", user_id, thread_id)
    )
    _assert(ambiguous_memory.planner_used, str(ambiguous_memory))
    _assert(
        [item.operation for item in ambiguous_memory.actions] == ["search_memory"],
        str(ambiguous_memory),
    )

    for pet_query in (
        "\u6211\u6709\u4ec0\u4e48\u5ba0\u7269",
        "\u6211\u6709\u54ea\u4e9b\u5ba0\u7269\u5417",
    ):
        pet_plan = await ActionPlanner().plan(_input(pet_query, user_id, thread_id))
        _assert(pet_plan.route_type == "fast_path", str(pet_plan))
        _assert(
            [item.operation for item in pet_plan.actions] == ["search_memory"],
            str(pet_plan),
        )
        _assert(pet_plan.actions[0].arguments.get("lookup_kind") == "pet_count", str(pet_plan))

    compound = (
        "\u5148\u8bb0\u4f4f\u6211\u559c\u6b22\u84dd\u8272\uff0c"
        "\u7136\u540e\u67e5\u4e00\u4e0b\u8c46\u74e3\u5173\u4e8e"
        "\u975e\u66b4\u529b\u6c9f\u901a\u7684\u8bc4\u8bba\uff0c"
        "\u518d\u63a8\u8350\u7c7b\u4f3c\u7684\u4e66\u7c4d"
    )
    compound_plan = await ActionPlanner().plan(_input(compound, user_id, thread_id))
    compound_operations = [item.operation for item in compound_plan.actions]
    _assert(
        compound_operations
        == ["capture_user_state", "search_memory", "web_search", "search_books"],
        str(compound_plan),
    )
    _assert(compound_plan.actions[0].arguments.get("raw_text") == "\u6211\u559c\u6b22\u84dd\u8272", str(compound_plan))
    _assert(
        compound_plan.actions[-1].arguments.get("query")
        == "\u975e\u66b4\u529b\u6c9f\u901a \u7c7b\u4f3c\u4e66\u7c4d \u63a8\u8350",
        str(compound_plan),
    )

    complex_request = (
        "\u6211\u559c\u6b22\u60ac\u7591\u4f46\u522b\u592a\u8840\u8165\uff0c"
        "\u770b\u770b\u6700\u8fd1\u4e24\u5e74\u53e3\u7891\u597d\u7684\uff0c"
        "\u6700\u597d\u6709\u4e2d\u6587\u7248\uff0c"
        "\u4f7f\u7528 deep research \u80fd\u529b"
    )
    complex_plan = await _OfflinePlanner().plan(
        _input(complex_request, user_id, thread_id)
    )
    _assert(complex_plan.complexity == "high", str(complex_plan))
    _assert(complex_plan.planner_used, str(complex_plan))
    _assert(complex_plan.source == "llm_planner_fallback", str(complex_plan))

    feedback = build_fast_action_plan(
        _input("\u300a\u4e09\u4f53\u300b\u6211\u5df2\u7ecf\u770b\u8fc7\u4e86", user_id, thread_id)
    )
    _assert(feedback is not None, "reading feedback was not planned")
    _assert(
        set(feedback.actions[0].arguments)
        == {"book_title", "interaction_type", "note"},
        str(feedback.actions[0].arguments),
    )


async def _verify_memory_runtime(
    user_id: uuid.UUID,
    first_thread: uuid.UUID,
    second_thread: uuid.UUID,
) -> None:
    name_turn = await prepare_runtime_turn(
        _input("\u6211\u662f\u51b0\u9732", user_id, first_thread)
    )
    _assert(name_turn.plan.intent == "memory_write", str(name_turn.plan))
    _assert(name_turn.receipt.status == "completed", str(name_turn.receipt))
    _assert(
        [item.operation for item in name_turn.receipt.actions]
        == ["capture_user_state"],
        str(name_turn.receipt),
    )
    name_answer = finalize_deterministic_receipt(name_turn.plan, name_turn.receipt)
    _assert("\u51b0\u9732" in name_answer.content, name_answer.content)

    lookup_turn = await prepare_runtime_turn(
        _input("\u6211\u662f\u8c01\uff1f", user_id, second_thread)
    )
    _assert(
        [item.operation for item in lookup_turn.receipt.actions] == ["search_memory"],
        str(lookup_turn.receipt),
    )
    _assert(lookup_turn.receipt.actions[0].system_executed, str(lookup_turn.receipt))
    _assert(lookup_turn.receipt.actions[0].output["result_count"] >= 1, str(lookup_turn.receipt))
    lookup_answer = finalize_deterministic_receipt(lookup_turn.plan, lookup_turn.receipt)
    _assert("\u51b0\u9732" in lookup_answer.content, lookup_answer.content)
    trace = receipt_trace_steps(lookup_turn.receipt)
    _assert(trace and trace[0]["tool_name"] == "search_memory", str(trace))

    garment_text = "\u6211\u6709\u4e00\u4ef6\u7ea2\u8272\u5916\u5957\uff0c\u653e\u5728\u8863\u67dc\u5de6\u8fb9"
    garment_input = _input(garment_text, user_id, first_thread)
    garment_decision = decide_fast_path(garment_input)
    _assert(
        garment_decision.handled
        and garment_decision.metadata.get("generic_user_state") is True,
        str(garment_decision),
    )
    garment_turn = await prepare_runtime_turn(garment_input)
    garment_output = garment_turn.receipt.actions[0].output
    _assert(garment_output["status"] == "saved_pending", str(garment_output))
    _assert(
        garment_output["memory"]["raw_text"] == garment_text,
        str(garment_output),
    )

    garment_lookup = await prepare_runtime_turn(
        _input("\u6211\u7684\u7ea2\u8272\u5916\u5957\u653e\u5728\u54ea\uff1f", user_id, second_thread)
    )
    search_output = garment_lookup.receipt.actions[0].output
    _assert(
        any(item.get("raw_text") == garment_text for item in search_output["memories"]),
        str(search_output),
    )

    turtle_text = "\u6211\u517b\u4e86\u4e00\u53ea\u4e4c\u9f9f\uff0c\u540d\u5b57\u53eb\u6162\u6162"
    turtle_turn = await prepare_runtime_turn(
        _input(turtle_text, user_id, first_thread)
    )
    turtle_output = turtle_turn.receipt.actions[0].output
    saved_raw = (turtle_output.get("memory") or {}).get("raw_text")
    captured = turtle_output.get("captured_count", 0)
    _assert(saved_raw == turtle_text or captured > 0, str(turtle_output))

    context_pack = await ContextBuilder().build(
        user_id=user_id,
        thread_id=second_thread,
        user_message="\u6211\u662f\u8c01\uff1f",
        messages=[],
        plan_receipt=lookup_turn.receipt.model_dump(mode="json"),
    )
    _assert(context_pack.runtime_receipt, str(context_pack))
    _assert(context_pack.metadata.get("hidden_memory_reads") is False, str(context_pack.metadata))


async def _run() -> None:
    _verify_contract_boundary()
    user_id = uuid.uuid4()
    first_thread = uuid.uuid4()
    second_thread = uuid.uuid4()
    await _insert_user_and_threads(user_id, [first_thread, second_thread])
    try:
        await _verify_planning_without_live_calls(user_id, second_thread)
        await _verify_memory_runtime(user_id, first_thread, second_thread)
        print("action-plan runtime verification passed")
    finally:
        await _delete_user(user_id)


async def _main(skip_migration: bool) -> None:
    load_dotenv()
    if not skip_migration:
        _init_postgres()
    init_embedding_model()
    await init_database()
    try:
        await _run()
    finally:
        await dispose_database()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-migration", action="store_true")
    args = parser.parse_args()
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(_main(skip_migration=args.skip_migration))


if __name__ == "__main__":
    main()
