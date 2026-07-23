"""Verify controlled research source collection.

This check avoids live web/provider calls. It verifies:
- collect_research_sources is gated by research intent
- source collection normalizes source records into observation batches
- collection logs search/visit research steps but does not write evidence
- explicit add_evidence + build_research_report admits verified claims
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import uuid
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from sqlalchemy import text

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.agents.tools import research as research_tools
from app.infra.database import dispose_database, get_database, init_database
from app.infra.llm.embedding import init_embedding_model
from app.services.tool_admission import reset_tool_admission_gate
from app.utils.logging import request_id_scope
from app.utils.turn_context import user_message_scope
from scripts.init_database import _init_postgres


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


async def _insert_temp_user_and_thread(
    user_id: uuid.UUID,
    thread_id: uuid.UUID,
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
            {"user_id": user_id, "display_name": "Research Source Verify"},
        )
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
                "title": "Research Source Verify",
            },
        )


async def _delete_temp_user(user_id: uuid.UUID) -> None:
    db = get_database()
    async with db.session() as session:
        await session.execute(
            text("DELETE FROM public.users WHERE id = :user_id"),
            {"user_id": user_id},
        )


async def _memory_event_count(user_id: uuid.UUID) -> int:
    db = get_database()
    async with db.session() as session:
        count = await session.scalar(
            text("SELECT COUNT(*) FROM public.memory_events WHERE user_id = :user_id"),
            {"user_id": user_id},
        )
        return int(count or 0)


async def _evidence_count(run_id: str) -> int:
    db = get_database()
    async with db.session() as session:
        count = await session.scalar(
            text("SELECT COUNT(*) FROM public.research_evidence WHERE run_id = :run_id"),
            {"run_id": run_id},
        )
        return int(count or 0)


async def _research_step_types(run_id: str) -> list[str]:
    db = get_database()
    async with db.session() as session:
        rows = await session.execute(
            text(
                """
                SELECT step_type
                FROM public.research_steps
                WHERE run_id = :run_id
                ORDER BY created_at ASC
                """
            ),
            {"run_id": run_id},
        )
        return [str(row[0]) for row in rows.fetchall()]


async def _start_research(**payload: Any) -> dict[str, Any]:
    return json.loads(await research_tools.start_research.ainvoke(payload))


async def _collect_sources(**payload: Any) -> dict[str, Any]:
    return json.loads(await research_tools.collect_research_sources.ainvoke(payload))


async def _add_evidence(**payload: Any) -> dict[str, Any]:
    return json.loads(await research_tools.add_evidence.ainvoke(payload))


async def _update_state(**payload: Any) -> dict[str, Any]:
    return json.loads(await research_tools.update_research_state.ainvoke(payload))


async def _build_report(**payload: Any) -> dict[str, Any]:
    return json.loads(await research_tools.build_research_report.ainvoke(payload))


async def _run_source_collection_flow() -> None:
    user_id = uuid.uuid4()
    thread_id = uuid.uuid4()

    await _insert_temp_user_and_thread(user_id, thread_id)
    try:
        reset_tool_admission_gate()
        with request_id_scope("verify-source-collection-blocked"):
            with user_message_scope("What is the style of Nonviolent Communication?"):
                blocked = await _collect_sources(
                    user_id=str(user_id),
                    run_id=str(uuid.uuid4()),
                    query="style question",
                    sources=[
                        {
                            "title": "Blocked Source",
                            "url": "https://example.test/blocked-source",
                            "claim": "This should not collect outside research intent.",
                            "excerpt": "Blocked.",
                        }
                    ],
                )
        _assert(blocked["status"] == "tool_blocked", str(blocked))
        _assert(
            "can_use_research_tools"
            in blocked["metadata"]["tool_admission"]["metadata"]["missing_policy_flags"],
            str(blocked["metadata"]["tool_admission"]),
        )

        memory_count_before = await _memory_event_count(user_id)
        reset_tool_admission_gate()
        with request_id_scope("verify-source-collection-allowed"):
            with user_message_scope(
                "Please deep research whether Example Novel is a warm fit."
            ):
                started = await _start_research(
                    user_id=str(user_id),
                    thread_id=str(thread_id),
                    objective="Assess Example Novel from controlled source records.",
                    mode="deep_research",
                    subquestions=["Is Example Novel warm and character-driven?"],
                    gaps=["Need source-backed evidence."],
                    next_actions=["Collect controlled source records."],
                    budget={"required_evidence_quality": "medium"},
                    stop_criteria=["One medium-quality claim is admitted."],
                )
                run_id = started["run"]["id"]
                collection = await _collect_sources(
                    user_id=str(user_id),
                    run_id=run_id,
                    query="Example Novel warm character-driven review",
                    subquestion="Is Example Novel warm and character-driven?",
                    provider_source="verify_source_collection",
                    rationale="Use controlled source records for research.",
                    sources=[
                        {
                            "title": "Reliable Review",
                            "url": "https://example.test/reliable-review",
                            "claim": "Example Novel is warm and character-driven.",
                            "content": (
                                "The review describes a gentle character-focused "
                                "story."
                            ),
                            "quality": "medium",
                            "relevance": 5,
                        },
                        {
                            "title": "Rejected Source",
                            "url": "https://example.test/rejected-source",
                            "content": "No explicit claim is present.",
                        },
                    ],
                    metadata={"trace_id": "verify_source_collection"},
                )

                _assert(
                    collection["result_mode"] == "research_source_collection",
                    str(collection),
                )
                _assert(
                    collection["contract_version"] == "research-source-collection-v1",
                    str(collection),
                )
                _assert(collection["status"] == "completed", str(collection))
                _assert(collection["metadata"]["writes_research_state"] is True, str(collection))
                _assert(collection["metadata"]["writes_evidence"] is False, str(collection))
                batch = collection["observation_batch"]
                _assert(batch["result_mode"] == "research_observation_batch", str(batch))
                _assert(batch["observation_count"] == 1, str(batch))
                _assert(len(batch["rejected_sources"]) == 1, str(batch))
                _assert(
                    batch["observations"][0]["metadata"]["provider_source"]
                    == "verify_source_collection",
                    str(batch["observations"][0]),
                )

                _assert(
                    await _evidence_count(run_id) == 0,
                    "source collection must not write evidence",
                )
                steps_after_collection = await _research_step_types(run_id)
                _assert("search" in steps_after_collection, str(steps_after_collection))
                _assert("visit" in steps_after_collection, str(steps_after_collection))
                _assert("add_evidence" not in steps_after_collection, str(steps_after_collection))

                observation = batch["observations"][0]
                await _add_evidence(
                    user_id=str(user_id),
                    run_id=run_id,
                    source_type=observation["source_type"],
                    source_title=observation["source_title"],
                    source_url=observation["source_url"],
                    claim=observation["claim"],
                    excerpt=observation["excerpt"],
                    quality=observation["quality"],
                    relevance=observation["relevance"],
                    metadata=observation["metadata"],
                    known_facts=[observation["claim"]],
                    next_actions=["Build a research report."],
                )
                await _update_state(
                    user_id=str(user_id),
                    run_id=run_id,
                    known_facts=[observation["claim"]],
                    gaps=[],
                    conflicts=[],
                    next_actions=["Build a research report."],
                    replace=True,
                )
                report = await _build_report(
                    user_id=str(user_id),
                    run_id=run_id,
                )

        _assert(await _memory_event_count(user_id) == memory_count_before, "no memory writes")
        _assert(await _evidence_count(run_id) == 1, "explicit evidence should be stored")
        _assert(report["result_mode"] == "research_report", str(report))
        _assert(report["report_status"] == "verified", str(report))
        _assert(
            report["verified_claims"][0]["claim"]
            == "Example Novel is warm and character-driven.",
            str(report["verified_claims"]),
        )
    finally:
        await _delete_temp_user(user_id)
        reset_tool_admission_gate()


async def _main(skip_migration: bool) -> None:
    load_dotenv()
    if not skip_migration:
        _init_postgres()
    init_embedding_model()
    await init_database()
    try:
        await _run_source_collection_flow()
    finally:
        await dispose_database()
    print("research source collection verification passed")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-migration", action="store_true")
    args = parser.parse_args()

    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(_main(skip_migration=args.skip_migration))


if __name__ == "__main__":
    main()
