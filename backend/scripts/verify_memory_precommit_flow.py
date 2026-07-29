r"""Verify the understand-before-write memory architecture against Postgres.

The verifier is provider-offline: every successful write is deterministically
understood before commit. It proves source/reference/completeness/persistence/
conflict gates, duplicate handling, raw-first rejection, active-only recall,
and the separation between current-conversation recall and durable memory.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import uuid
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import text


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.infra.database import dispose_database, get_database, init_database
from app.infra.llm.embedding import init_embedding_model
from app.models.memory import MemoryEventRecord
from app.schemas.chat import UserInput
from app.services.agent_runtime.coordinator import prepare_runtime_turn
from app.services.agent_runtime.finalizer import finalize_deterministic_receipt
from app.services.agent_runtime.planner import ActionPlanner
from app.services.memory import get_memory_orchestrator
from app.services.memory.identity import resolve_current_name
from app.services.memory.user_state import persist_raw_user_state
from scripts.init_database import _init_postgres


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def _input(
    content: str,
    *,
    user_id: uuid.UUID,
    thread_id: uuid.UUID,
    turns: list[dict[str, object]] | None = None,
    pending: dict[str, object] | None = None,
) -> UserInput:
    custom_data = None
    if turns is not None or pending is not None:
        custom_data = {
            "routing_context": {
                "conversation_turns": turns or [],
                "recent_user_messages": [
                    str(turn["content"])
                    for turn in (turns or [])
                    if turn.get("role") == "user"
                ],
                "pending_memory_write": pending,
            }
        }
    return UserInput(
        content=content,
        user_id=user_id,
        thread_id=thread_id,
        request_id=f"precommit-{uuid.uuid4()}",
        custom_data=custom_data,
    )


async def _seed(
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
            {
                "user_id": user_id,
                "display_name": "Precommit Memory Verify",
            },
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
                    "title": "Precommit Memory Verify",
                },
            )


async def _cleanup(user_id: uuid.UUID) -> None:
    db = get_database()
    async with db.session() as session:
        await session.execute(
            text("DELETE FROM public.users WHERE id = :user_id"),
            {"user_id": user_id},
        )


async def _event_count(user_id: uuid.UUID) -> int:
    result = await get_memory_orchestrator().list_memory_events(
        user_id=user_id,
        include_superseded=True,
        include_audit=True,
        limit=100,
    )
    return result.total


async def _insert_legacy_pending(
    *,
    user_id: uuid.UUID,
    thread_id: uuid.UUID,
) -> uuid.UUID:
    record = MemoryEventRecord(
        user_id=user_id,
        thread_id=thread_id,
        type="state",
        subject="object",
        value="legacy raw proposal",
        polarity="neutral",
        confidence=0.5,
        source="chat_turn",
        metadata_json={
            "user_state": {
                "status": "pending",
                "category": "relation",
                "state_key": "relation.legacy.pending",
                "summary": "",
                "raw_text": "把这个记住",
                "state_value": {},
                "relation": {},
                "use_when": [],
            }
        },
    )
    db = get_database()
    async with db.session() as session:
        session.add(record)
        await session.flush()
        record_id = record.id
    return record_id


async def _run() -> None:
    user_id = uuid.uuid4()
    clarification_user_id = uuid.uuid4()
    write_thread = uuid.uuid4()
    recall_thread = uuid.uuid4()
    clarification_thread = uuid.uuid4()
    await _seed(user_id, [write_thread, recall_thread])
    await _seed(clarification_user_id, [clarification_thread])
    try:
        incomplete = await prepare_runtime_turn(
            _input(
                "记住我的名字",
                user_id=clarification_user_id,
                thread_id=clarification_thread,
            )
        )
        incomplete_output = incomplete.receipt.actions[0].output
        _assert(
            incomplete_output["status"] == "clarification_required",
            str(incomplete_output),
        )
        pending = incomplete_output.get("pending_clarification")
        _assert(isinstance(pending, dict), str(incomplete_output))
        _assert(
            await _event_count(clarification_user_id) == 0,
            "clarification proposal entered durable memory",
        )
        completed = await prepare_runtime_turn(
            _input(
                "小雨",
                user_id=clarification_user_id,
                thread_id=clarification_thread,
                pending=pending,
            )
        )
        completed_output = completed.receipt.actions[0].output
        _assert(
            completed_output["status"] == "committed",
            str(completed_output),
        )
        clarified_current = (
            await get_memory_orchestrator().list_current_memories(
                user_id=clarification_user_id,
                limit=100,
            )
        )
        _assert(
            resolve_current_name(clarified_current.memories) == "小雨",
            str(clarified_current),
        )

        greeting = "你好我是冰露"
        first = await prepare_runtime_turn(
            _input(
                greeting,
                user_id=user_id,
                thread_id=write_thread,
            )
        )
        _assert(
            [action.operation for action in first.plan.actions]
            == ["process_memory_write_request"],
            str(first.plan),
        )
        first_output = first.receipt.actions[0].output
        _assert(first_output["status"] == "committed", str(first_output))
        first_answer = finalize_deterministic_receipt(
            first.plan,
            first.receipt,
        )
        _assert("你的名字是冰露" in first_answer.content, first_answer.content)

        current = await get_memory_orchestrator().list_current_memories(
            user_id=user_id,
            limit=100,
        )
        _assert(current.total == 1, str(current))
        name_memory = current.memories[0]
        _assert(name_memory.state_status == "active", str(name_memory))
        _assert(name_memory.state_key == "profile.name", str(name_memory))
        _assert(name_memory.state_value == {"name": "冰露"}, str(name_memory))
        _assert(resolve_current_name(current.memories) == "冰露", str(current))
        precommit = name_memory.metadata.get("precommit") or {}
        _assert(
            all(
                precommit.get(gate) is True
                for gate in (
                    "source_identified",
                    "reference_resolved",
                    "completeness_validated",
                    "persistence_approved",
                    "conflict_checked",
                )
            ),
            str(precommit),
        )

        prior_turns = [
            {
                "role": "user",
                "turn_offset": -2,
                "content": greeting,
            },
            {
                "role": "assistant",
                "turn_offset": -1,
                "content": "你好，冰露！",
            },
        ]
        repeated = await prepare_runtime_turn(
            _input(
                "记住我的名字",
                user_id=user_id,
                thread_id=write_thread,
                turns=prior_turns,
            )
        )
        repeated_output = repeated.receipt.actions[0].output
        _assert(
            repeated_output["status"] == "noop_duplicate",
            str(repeated_output),
        )
        repeated_answer = finalize_deterministic_receipt(
            repeated.plan,
            repeated.receipt,
        )
        _assert("不需要重复保存" in repeated_answer.content, repeated_answer.content)
        _assert(await _event_count(user_id) == 1, "duplicate created a row")

        raw_first = await persist_raw_user_state(
            user_id=user_id,
            thread_id=write_thread,
            raw_text="把这个记住",
            explicit=True,
            schedule_organization=False,
        )
        _assert(raw_first.status == "rejected_raw_first", str(raw_first))
        _assert(raw_first.memory is None, str(raw_first))
        _assert(await _event_count(user_id) == 1, "raw-first path wrote a row")

        unresolved = await ActionPlanner().plan(
            _input(
                "把这个记住",
                user_id=user_id,
                thread_id=recall_thread,
            )
        )
        interaction = (
            unresolved.metadata.get("routing_decision", {})
            .get("interaction_decision", {})
        )
        _assert(not unresolved.actions, str(unresolved))
        _assert(
            interaction.get("status") == "clarification_required",
            str(interaction),
        )
        _assert(await _event_count(user_id) == 1, "clarification wrote a row")

        pending_id = await _insert_legacy_pending(
            user_id=user_id,
            thread_id=write_thread,
        )
        visible = await get_memory_orchestrator().list_current_memories(
            user_id=user_id,
            limit=100,
        )
        _assert(
            all(memory.id != pending_id for memory in visible.memories),
            str(visible),
        )
        _assert(resolve_current_name(visible.memories) == "冰露", str(visible))

        recall_turns = [
            {
                "role": "user",
                "turn_offset": -4,
                "content": greeting,
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
                "content": repeated_answer.content,
            },
        ]
        before_recall = await _event_count(user_id)
        recalled = await prepare_runtime_turn(
            _input(
                "我刚才跟你说什么了",
                user_id=user_id,
                thread_id=recall_thread,
                turns=recall_turns,
            )
        )
        _assert(
            [action.operation for action in recalled.plan.actions]
            == ["recall_recent_conversation"],
            str(recalled.plan),
        )
        recall_answer = finalize_deterministic_receipt(
            recalled.plan,
            recalled.receipt,
        )
        _assert(greeting in recall_answer.content, recall_answer.content)
        _assert("记住我的名字" in recall_answer.content, recall_answer.content)
        _assert(
            await _event_count(user_id) == before_recall,
            "conversation recall mutated durable memory",
        )

        print("memory precommit verification passed")
        print("committed_state_key=profile.name")
        print("duplicate_status=noop_duplicate")
        print("raw_first_status=rejected_raw_first")
        print("unresolved_status=clarification_required")
        print("clarification_continuation=committed")
        print("conversation_operation=recall_recent_conversation")
    finally:
        await _cleanup(user_id)
        await _cleanup(clarification_user_id)


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
    asyncio.run(_main(args.skip_migration))


if __name__ == "__main__":
    main()
