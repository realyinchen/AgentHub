r"""Verify the ActionPlan -> SystemRuntime -> PlanReceipt architecture.

This check intentionally avoids live web, research, and LLM provider calls. It
verifies deterministic planning, runtime-owned context injection, canonical
pre-commit memory writes, cross-conversation recall, visible memory receipts,
and on-demand planner selection.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import uuid
from pathlib import Path
from unittest.mock import patch

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
from app.services.routing.funnel import RoutingFunnel
from app.services.routing.semantic import InMemorySemanticRecall
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


class _NoLiveVectorSemantic(InMemorySemanticRecall):
    async def _vector_candidates(self, text: str):
        del text
        return []


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

    _assert(
        not hasattr(fast_path, "try_handle_fast_path"),
        "legacy direct-answer fast path still exists",
    )
    planner_source = (
        BACKEND_DIR / "app" / "services" / "agent_runtime" / "planner.py"
    ).read_text(encoding="utf-8")
    _assert(
        "turn_execution" not in planner_source,
        "planner still imports the legacy routing/execution module",
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

    stable_authorship = await ActionPlanner().plan(
        _input("\u300a\u4e09\u4f53\u300b\u7684\u4f5c\u8005\u662f\u8c01\uff1f", user_id, thread_id)
    )
    _assert(not stable_authorship.planner_used, str(stable_authorship))
    _assert(not stable_authorship.actions, str(stable_authorship))

    stable_explanation = await ActionPlanner().plan(
        _input("\u4ec0\u4e48\u662f\u9012\u5f52\uff1f", user_id, thread_id)
    )
    _assert(not stable_explanation.planner_used, str(stable_explanation))
    _assert(not stable_explanation.actions, str(stable_explanation))

    ambiguous_memory = await ActionPlanner().plan(
        _input("\u6211\u4ec0\u4e48\u65f6\u5019\u4ea4\u623f\u79df\uff1f", user_id, thread_id)
    )
    _assert(not ambiguous_memory.planner_used, str(ambiguous_memory))
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
        == [
            "process_memory_write_request",
            "search_memory",
            "web_search",
            "search_books",
        ],
        str(compound_plan),
    )
    memory_request = compound_plan.actions[0].arguments.get("request") or {}
    _assert(
        memory_request.get("utterance")
        == "\u5148\u8bb0\u4f4f\u6211\u559c\u6b22\u84dd\u8272",
        str(compound_plan),
    )
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
    complex_plan = await ActionPlanner().plan(
        _input(complex_request, user_id, thread_id)
    )
    _assert(complex_plan.complexity == "high", str(complex_plan))
    _assert(not complex_plan.planner_used, str(complex_plan))
    _assert(
        complex_plan.metadata.get("planner_required") is True,
        str(complex_plan),
    )
    _assert(
        complex_plan.metadata.get("planning_strategy")
        == "explicit_runtime_search_tasks",
        str(complex_plan),
    )
    _assert(complex_plan.source == "routing_decision", str(complex_plan))
    _assert(complex_plan.response_mode == "receipt", str(complex_plan))

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
    _assert(name_turn.plan.intent == "memory_update", str(name_turn.plan))
    _assert(name_turn.receipt.status == "completed", str(name_turn.receipt))
    _assert(
        [item.operation for item in name_turn.receipt.actions]
        == ["process_memory_write_request"],
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

    correction_turn = await prepare_runtime_turn(
        _input(
            "\u6211\u73b0\u5728\u4e0d\u53eb\u51b0\u9732\uff0c\u6211\u73b0\u5728\u53eb\u9c81\u73ed",
            user_id,
            first_thread,
        )
    )
    _assert(
        [item.operation for item in correction_turn.receipt.actions]
        == ["process_memory_write_request"],
        str(correction_turn.receipt),
    )
    corrected_lookup = await prepare_runtime_turn(
        _input("\u6211\u662f\u8c01\uff1f", user_id, second_thread)
    )
    corrected_answer = finalize_deterministic_receipt(
        corrected_lookup.plan,
        corrected_lookup.receipt,
    )
    _assert("\u9c81\u73ed" in corrected_answer.content, corrected_answer.content)

    unresolved = await ActionPlanner().plan(
        _input("\u628a\u8fd9\u4e2a\u8bb0\u4f4f", user_id, second_thread)
    )
    _assert(not unresolved.actions, str(unresolved))
    _assert(
        unresolved.metadata.get("routing_decision", {})
        .get("interaction_decision", {})
        .get("status")
        == "clarification_required",
        str(unresolved),
    )

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
        offline_funnel = RoutingFunnel(
            semantic_provider=_NoLiveVectorSemantic()
        )
        with patch(
            "app.services.agent_runtime.planner.get_routing_funnel",
            return_value=offline_funnel,
        ):
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
