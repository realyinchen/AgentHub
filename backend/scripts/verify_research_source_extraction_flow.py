"""Verify controlled research source extraction.

This check avoids live web/provider calls. It verifies:
- extract_research_source_records is gated by research intent
- approved search/visit documents become app-owned source records
- extraction is read-only and does not write research state or evidence
- extracted records can flow through collection, evidence admission, and report
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
            {"user_id": user_id, "display_name": "Source Extraction Verify"},
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
                "title": "Source Extraction Verify",
            },
        )


async def _delete_temp_user(user_id: uuid.UUID) -> None:
    db = get_database()
    async with db.session() as session:
        await session.execute(
            text("DELETE FROM public.users WHERE id = :user_id"),
            {"user_id": user_id},
        )


async def _research_step_count(run_id: str) -> int:
    db = get_database()
    async with db.session() as session:
        count = await session.scalar(
            text("SELECT COUNT(*) FROM public.research_steps WHERE run_id = :run_id"),
            {"run_id": run_id},
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


async def _extract_sources(**payload: Any) -> dict[str, Any]:
    return json.loads(await research_tools.extract_research_source_records.ainvoke(payload))


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


async def _run_source_extraction_flow() -> None:
    user_id = uuid.uuid4()
    thread_id = uuid.uuid4()

    await _insert_temp_user_and_thread(user_id, thread_id)
    try:
        reset_tool_admission_gate()
        with request_id_scope("verify-source-extraction-blocked"):
            with user_message_scope("What is the style of Nonviolent Communication?"):
                blocked = await _extract_sources(
                    query="style question",
                    documents=[
                        {
                            "title": "Blocked Source",
                            "url": "https://example.test/blocked",
                            "content": "Blocked Source says this should not run.",
                        }
                    ],
                )
        _assert(blocked["status"] == "tool_blocked", str(blocked))
        _assert(
            "can_use_research_tools"
            in blocked["metadata"]["tool_admission"]["metadata"]["missing_policy_flags"],
            str(blocked["metadata"]["tool_admission"]),
        )

        reset_tool_admission_gate()
        with request_id_scope("verify-source-extraction"):
            with user_message_scope(
                "Please deep research whether Example Novel is a warm fit."
            ):
                started = await _start_research(
                    user_id=str(user_id),
                    thread_id=str(thread_id),
                    objective="Assess Example Novel from extracted source documents.",
                    mode="deep_research",
                    subquestions=["Is Example Novel warm and character-driven?"],
                    gaps=["Need extracted source-backed evidence."],
                    next_actions=["Extract source records from search results."],
                    budget={"required_evidence_quality": "medium"},
                    stop_criteria=["One medium-quality claim is admitted."],
                )
                run_id = started["run"]["id"]
                step_count_before = await _research_step_count(run_id)
                extraction = await _extract_sources(
                    query="Example Novel warm character-driven review",
                    subquestion="Is Example Novel warm and character-driven?",
                    provider_source="verify_source_extraction",
                    documents=[
                        {
                            "title": "Reliable Review",
                            "url": "https://example.test/reliable-review",
                            "content": (
                                "Example Novel is warm and character-driven. "
                                "The review also says the pacing is gentle."
                            ),
                            "quality": "medium",
                            "relevance": 5,
                        },
                        {
                            "title": "Off Topic Review",
                            "url": "https://example.test/off-topic",
                            "content": "This page only discusses cover typography.",
                            "quality": "medium",
                            "relevance": 2,
                        },
                        {
                            "content": "Example Novel is warm but lacks source metadata.",
                        },
                    ],
                    metadata={"trace_id": "verify_source_extraction"},
                )

                _assert(
                    extraction["result_mode"] == "research_source_extraction",
                    str(extraction),
                )
                _assert(
                    extraction["contract_version"] == "research-source-extraction-v1",
                    str(extraction),
                )
                _assert(extraction["status"] == "partial", str(extraction))
                _assert(extraction["extracted_count"] == 1, str(extraction))
                _assert(len(extraction["rejected_documents"]) == 2, str(extraction))
                _assert(
                    extraction["metadata"]["writes_research_state"] is False,
                    str(extraction["metadata"]),
                )
                _assert(
                    await _research_step_count(run_id) == step_count_before,
                    "source extraction must not write research steps",
                )
                _assert(
                    await _evidence_count(run_id) == 0,
                    "source extraction must not write evidence",
                )
                observation_batch = extraction["observation_batch"]
                _assert(
                    observation_batch["result_mode"] == "research_observation_batch",
                    str(observation_batch),
                )
                _assert(observation_batch["observation_count"] == 1, str(observation_batch))
                observation = observation_batch["observations"][0]
                _assert(
                    observation["claim"]
                    == "Example Novel is warm and character-driven.",
                    str(observation),
                )
                _assert(
                    observation["metadata"]["source_extraction"][
                        "claim_is_source_sentence"
                    ]
                    is True,
                    str(observation["metadata"]),
                )

                collection = await _collect_sources(
                    user_id=str(user_id),
                    run_id=run_id,
                    query=extraction["query"],
                    subquestion=extraction["subquestion"],
                    provider_source="verify_source_extraction",
                    sources=extraction["source_records"],
                )
                _assert(
                    collection["result_mode"] == "research_source_collection",
                    str(collection),
                )
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
                    next_actions=["Build a report."],
                )
                await _update_state(
                    user_id=str(user_id),
                    run_id=run_id,
                    known_facts=[observation["claim"]],
                    gaps=[],
                    conflicts=[],
                    next_actions=["Build a report."],
                    replace=True,
                )
                report = await _build_report(user_id=str(user_id), run_id=run_id)

        _assert(await _evidence_count(run_id) == 1, "admitted evidence should be stored")
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
        await _run_source_extraction_flow()
    finally:
        await dispose_database()
    print("research source extraction verification passed")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-migration", action="store_true")
    args = parser.parse_args()

    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(_main(skip_migration=args.skip_migration))


if __name__ == "__main__":
    main()
