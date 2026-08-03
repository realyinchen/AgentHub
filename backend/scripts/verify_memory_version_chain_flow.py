"""Verify canonical memory create/correct/noop/forget chains in PostgreSQL."""

# ruff: noqa: E402

from __future__ import annotations

import asyncio
import json
import sys
import uuid
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import func, select, text


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

load_dotenv(BACKEND_DIR / ".env")

from app.infra.database import (
    dispose_database,
    get_database,
    init_database_connection,
)
from app.models.memory import MemoryEventRecord
from app.schemas.chat import UserInput
from app.services.agent_core.capabilities import CapabilityRegistry
from app.services.agent_core.contracts import (
    ControllerOutput,
    ControllerToolCall,
)
from app.services.agent_core.core_capabilities import (
    CoreCapabilityAvailability,
)
from app.services.agent_core.harness import AgentCoreHarness
from app.services.agent_runtime.contracts import ExecutionContext
from app.services.conversation import ConversationJournalService
from app.services.memory import (
    MemoryAssertionProposal,
    MemoryCanonicalizer,
    MemoryVersionCommitCommand,
    MemoryVersionIdempotencyConflict,
    MemoryVersionStore,
)
from scripts.init_database import _init_postgres


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


async def _seed(*, user_id: uuid.UUID, thread_id: uuid.UUID) -> None:
    db = get_database()
    async with db.session() as session:
        await session.execute(
            text(
                """
                INSERT INTO public.users (id, display_name, is_mock_user)
                VALUES (:user_id, :display_name, true)
                """
            ),
            {
                "user_id": user_id,
                "display_name": "Memory Version Verify",
            },
        )
        await session.execute(
            text(
                """
                INSERT INTO public.conversations (thread_id, user_id, title)
                VALUES (:thread_id, :user_id, :title)
                """
            ),
            {
                "thread_id": thread_id,
                "user_id": user_id,
                "title": "Memory Version Verify",
            },
        )


async def _user_event(
    *,
    user_id: uuid.UUID,
    thread_id: uuid.UUID,
    request_id: str,
    content: str,
):
    db = get_database()
    async with db.session() as session:
        return await ConversationJournalService().record_user_message(
            session,
            UserInput(
                content=content,
                user_id=user_id,
                thread_id=thread_id,
                request_id=request_id,
            ),
        )


def _canonical_name(name: str, source: str):
    result = MemoryCanonicalizer().canonicalize(
        [
            MemoryAssertionProposal(
                subject="self",
                predicate="name",
                value={"name": name},
                evidence_quote=source,
            )
        ],
        source_text=source,
    )
    _assert(result.status == "ready", str(result))
    return result.facts[0]


async def _commit(
    *,
    user_id: uuid.UUID,
    thread_id: uuid.UUID,
    source_event_id: uuid.UUID,
    receipt_id: str,
    fact,
):
    db = get_database()
    async with db.session() as session:
        return await MemoryVersionStore(session).commit(
            MemoryVersionCommitCommand(
                facts=[fact],
                source_event_id=source_event_id,
                receipt_id=receipt_id,
            ),
            user_id=user_id,
            thread_id=thread_id,
        )


async def _cleanup(user_id: uuid.UUID) -> None:
    db = get_database()
    async with db.session() as session:
        await session.execute(
            text("DELETE FROM public.users WHERE id = :user_id"),
            {"user_id": user_id},
        )


async def _run() -> dict:
    user_id = uuid.uuid4()
    thread_id = uuid.uuid4()
    harness = AgentCoreHarness(
        registry=CapabilityRegistry(
            core_availability=CoreCapabilityAvailability.all_enabled()
        )
    )
    await _seed(user_id=user_id, thread_id=thread_id)
    try:
        await _user_event(
            user_id=user_id,
            thread_id=thread_id,
            request_id="memory-v1",
            content="I am 冰露",
        )
        first_fact = _canonical_name("冰露", "I am 冰露")
        controller_result = await harness.run(
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
            context=ExecutionContext(
                user_id=user_id,
                thread_id=thread_id,
                request_id="memory-v1",
            ),
            user_input=UserInput(
                content="I am 冰露",
                user_id=user_id,
                thread_id=thread_id,
                request_id="memory-v1",
            ),
        )
        _assert(controller_result.receipt is not None, str(controller_result))
        _assert(controller_result.answer is not None, str(controller_result))
        _assert(
            controller_result.answer.receipt_backed
            and "已记录" in controller_result.answer.content,
            str(controller_result.answer),
        )
        created_output = controller_result.receipt.actions[0].output
        _assert(
            created_output["mutations"][0]["status"] == "created",
            str(created_output),
        )
        _assert(
            created_output["mutations"][0]["version"]["version_no"] == 1,
            str(created_output),
        )

        duplicate_source = await _user_event(
            user_id=user_id,
            thread_id=thread_id,
            request_id="memory-duplicate",
            content="I am 冰露",
        )
        duplicate = await _commit(
            user_id=user_id,
            thread_id=thread_id,
            source_event_id=duplicate_source.id,
            receipt_id="memory-receipt-duplicate",
            fact=first_fact,
        )
        _assert(
            duplicate.status == "noop_duplicate"
            and duplicate.mutations[0].version.version_no == 1,
            str(duplicate),
        )

        corrected_text = "我现在不叫冰露，我现在叫鲁班"
        await _user_event(
            user_id=user_id,
            thread_id=thread_id,
            request_id="memory-v2",
            content=corrected_text,
        )
        corrected_result = await harness.run(
            ControllerOutput(
                mode="capability_proposals",
                tool_calls=[
                    ControllerToolCall(
                        call_id="correct-name",
                        name="remember_memory",
                        arguments={
                            "assertions": [
                                {
                                    "subject": "self",
                                    "predicate": "name",
                                    "value": {"name": "鲁班"},
                                    "qualifiers": {},
                                    "evidence_quote": "我现在叫鲁班",
                                }
                            ]
                        },
                    )
                ],
            ),
            goal=corrected_text,
            context=ExecutionContext(
                user_id=user_id,
                thread_id=thread_id,
                request_id="memory-v2",
            ),
            user_input=UserInput(
                content=corrected_text,
                user_id=user_id,
                thread_id=thread_id,
                request_id="memory-v2",
            ),
        )
        _assert(corrected_result.receipt is not None, str(corrected_result))
        _assert(corrected_result.answer is not None, str(corrected_result))
        corrected_output = corrected_result.receipt.actions[0].output
        corrected_receipt_id = str(corrected_output["receipt_id"])
        _assert(
            corrected_output["mutations"][0]["status"] == "revised",
            str(corrected_output),
        )
        _assert(
            corrected_output["mutations"][0]["version"]["version_no"] == 2,
            str(corrected_output),
        )
        _assert(
            "已根据你的最新表述更新长期记忆"
            in corrected_result.answer.content,
            str(corrected_result.answer),
        )

        corrected_search = await harness.run(
            ControllerOutput(
                mode="capability_proposals",
                tool_calls=[
                    ControllerToolCall(
                        call_id="search-corrected-name",
                        name="search_memory",
                        arguments={"predicate": "name", "query": ""},
                    )
                ],
            ),
            goal="我是谁？",
            context=ExecutionContext(
                user_id=user_id,
                thread_id=thread_id,
                request_id="memory-search-v2",
            ),
        )
        _assert(corrected_search.answer is not None, str(corrected_search))
        _assert(
            "鲁班" in corrected_search.answer.content
            and "冰露" not in corrected_search.answer.content,
            str(corrected_search.answer),
        )

        receipt_conflict_source = await _user_event(
            user_id=user_id,
            thread_id=thread_id,
            request_id="memory-receipt-conflict",
            content="I am 冰露",
        )
        try:
            await _commit(
                user_id=user_id,
                thread_id=thread_id,
                source_event_id=receipt_conflict_source.id,
                receipt_id=corrected_receipt_id,
                fact=first_fact,
            )
        except MemoryVersionIdempotencyConflict:
            pass
        else:
            raise AssertionError("receipt reuse with another fact was accepted")

        concurrent_sources = await asyncio.gather(
            _user_event(
                user_id=user_id,
                thread_id=thread_id,
                request_id="memory-v3-a",
                content="I am 星露",
            ),
            _user_event(
                user_id=user_id,
                thread_id=thread_id,
                request_id="memory-v3-b",
                content="I am 星露",
            ),
        )
        concurrent_fact = _canonical_name("星露", "I am 星露")
        concurrent_receipts = await asyncio.gather(
            _commit(
                user_id=user_id,
                thread_id=thread_id,
                source_event_id=concurrent_sources[0].id,
                receipt_id="memory-receipt-v3-a",
                fact=concurrent_fact,
            ),
            _commit(
                user_id=user_id,
                thread_id=thread_id,
                source_event_id=concurrent_sources[1].id,
                receipt_id="memory-receipt-v3-b",
                fact=concurrent_fact,
            ),
        )
        _assert(
            sorted(
                receipt.mutations[0].status
                for receipt in concurrent_receipts
            )
            == ["noop_duplicate", "revised"],
            str(concurrent_receipts),
        )

        search_result = await harness.run(
            ControllerOutput(
                mode="capability_proposals",
                tool_calls=[
                    ControllerToolCall(
                        call_id="search-name",
                        name="search_memory",
                        arguments={"predicate": "name", "query": ""},
                    )
                ],
            ),
            goal="我是谁？",
            context=ExecutionContext(
                user_id=user_id,
                thread_id=thread_id,
                request_id="memory-search",
            ),
        )
        _assert(search_result.answer is not None, str(search_result))
        _assert(
            "星露" in search_result.answer.content,
            str(search_result.answer),
        )

        await _user_event(
            user_id=user_id,
            thread_id=thread_id,
            request_id="memory-forget",
            content="忘记我的名字",
        )
        forget_result = await harness.run(
            ControllerOutput(
                mode="capability_proposals",
                tool_calls=[
                    ControllerToolCall(
                        call_id="forget-name",
                        name="forget_memory",
                        arguments={
                            "targets": [
                                {
                                    "subject": "self",
                                    "predicate": "name",
                                    "identity": {},
                                    "qualifiers": {},
                                    "evidence_quote": "忘记我的名字",
                                }
                            ]
                        },
                    )
                ],
            ),
            goal="忘记我的名字",
            context=ExecutionContext(
                user_id=user_id,
                thread_id=thread_id,
                request_id="memory-forget",
            ),
            user_input=UserInput(
                content="忘记我的名字",
                user_id=user_id,
                thread_id=thread_id,
                request_id="memory-forget",
            ),
        )
        _assert(forget_result.receipt is not None, str(forget_result))
        _assert(forget_result.answer is not None, str(forget_result))
        _assert(
            "标记为遗忘" in forget_result.answer.content,
            str(forget_result.answer),
        )
        forgotten_output = forget_result.receipt.actions[0].output
        forgotten_version = forgotten_output["mutations"][0]["version"]
        _assert(
            forgotten_output["mutations"][0]["status"] == "forgotten",
            str(forgotten_output),
        )
        _assert(forgotten_version["version_no"] == 4, str(forgotten_output))
        _assert(forgotten_version["is_tombstone"], str(forgotten_output))

        db = get_database()
        async with db.session() as session:
            store = MemoryVersionStore(session)
            current = await store.list_current(user_id=user_id)
            history = await store.history(
                user_id=user_id,
                memory_key=first_fact.memory_key,
            )
            head_count = await session.scalar(
                select(func.count())
                .select_from(MemoryEventRecord)
                .where(
                    MemoryEventRecord.user_id == user_id,
                    MemoryEventRecord.memory_key == first_fact.memory_key,
                    MemoryEventRecord.superseded_by.is_(None),
                )
            )
        _assert(current == [], str(current))
        _assert(
            [item.version_no for item in history] == [1, 2, 3, 4],
            str(history),
        )
        _assert(
            [item.operation for item in history]
            == ["create", "correct", "correct", "forget"],
            str(history),
        )
        _assert(head_count == 1, f"active chain heads={head_count}")
        _assert(
            all(
                item.valid_to is not None
                for item in history[:-1]
            )
            and history[-1].valid_to is None,
            "version validity interval is broken",
        )
        return {
            "status": "passed",
            "fixture_registry": "all_enabled_explicit",
            "cases": [
                {
                    "case_id": "identity_update",
                    "input": "我现在不叫冰露，我现在叫鲁班",
                    "expected_capability": "remember_memory",
                    "operation": "remember_memory_v2",
                    "mutation_status": "revised",
                    "version_no": 2,
                    "status": "passed",
                },
                {
                    "case_id": "identity_read",
                    "input": "我是谁？",
                    "expected_capability": "search_memory",
                    "operation": "search_memory_v2",
                    "current_name": "鲁班",
                    "superseded_name_exposed": False,
                    "status": "passed",
                },
            ],
        }
    finally:
        await _cleanup(user_id)


async def _main_async() -> dict:
    await init_database_connection()
    try:
        return await _run()
    finally:
        await dispose_database()


def main() -> None:
    _init_postgres()
    evidence = asyncio.run(_main_async())
    print("memory version chain verification passed")
    print("duplicate_versions_created=0")
    print("active_heads=1")
    print("concurrent_revision=linear")
    print("forget=tombstone")
    print(json.dumps(evidence, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
