"""Verify controlled local Python research analysis.

This check avoids live network calls and does not execute user code. It
verifies:
- analyze_research_data is gated by Deep Search / Deep Research intent
- supplied records become research-python-analysis-v1 plus nested observations
- analysis is read-only for app state
- produced findings can flow through collection, evidence admission, report,
  and final-answer projection
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


VERIFIED_CLAIM_FRAGMENT = "field 'score' has 3 numeric values"


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
            {"user_id": user_id, "display_name": "Research Python Analysis Verify"},
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
                "title": "Research Python Analysis Verify",
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


async def _start_research(**payload: Any) -> dict[str, Any]:
    return json.loads(await research_tools.start_research.ainvoke(payload))


async def _analyze_data(**payload: Any) -> dict[str, Any]:
    return json.loads(await research_tools.analyze_research_data.ainvoke(payload))


async def _collect_sources(**payload: Any) -> dict[str, Any]:
    return json.loads(await research_tools.collect_research_sources.ainvoke(payload))


async def _add_evidence(**payload: Any) -> dict[str, Any]:
    return json.loads(await research_tools.add_evidence.ainvoke(payload))


async def _finalize_answer(**payload: Any) -> dict[str, Any]:
    return json.loads(await research_tools.finalize_research_answer.ainvoke(payload))


async def _run_python_analysis_flow() -> None:
    user_id = uuid.uuid4()
    thread_id = uuid.uuid4()
    await _insert_temp_user_and_thread(user_id, thread_id)
    try:
        reset_tool_admission_gate()
        with request_id_scope("verify-python-analysis-blocked"):
            with user_message_scope("What is the style of Nonviolent Communication?"):
                blocked = await _analyze_data(
                    query="Example supplied scores",
                    dataset_title="Blocked supplied records",
                    records=[{"title": "Example", "score": 4.5}],
                )
        _assert(blocked["status"] == "tool_blocked", str(blocked))
        _assert(blocked["result_mode"] == "research_python_analysis", str(blocked))
        _assert(blocked["metadata"]["executes_user_code"] is False, str(blocked))
        _assert(blocked["metadata"]["reads_files"] is False, str(blocked))
        _assert(blocked["metadata"]["network_access"] is False, str(blocked))

        reset_tool_admission_gate()
        with request_id_scope("verify-python-analysis-flow"):
            with user_message_scope(
                "Please deep research the supplied recommendation scores."
            ):
                started = await _start_research(
                    user_id=str(user_id),
                    thread_id=str(thread_id),
                    objective="Analyze supplied recommendation score evidence.",
                    mode="deep_research",
                    subquestions=["What do the supplied scores show?"],
                    gaps=[],
                    next_actions=["Analyze the supplied structured records."],
                    budget={"required_evidence_quality": "medium"},
                    stop_criteria=["One medium-quality analysis finding."],
                )
                run_id = started["run"]["id"]
                memory_count_before = await _memory_event_count(user_id)
                step_count_before = await _research_step_count(run_id)
                evidence_count_before = await _evidence_count(run_id)

                analysis = await _analyze_data(
                    query="Analyze supplied recommendation scores",
                    subquestion="What do the supplied scores show?",
                    dataset_title="Reader response score table",
                    source_type="manual",
                    records=[
                        {"candidate": "Example Novel", "score": 4.8, "status": "kept"},
                        {"candidate": "Other Novel", "score": 3.2, "status": "filtered"},
                        {"candidate": "Third Novel", "score": 4.1, "status": "kept"},
                    ],
                    focus_fields=["score", "status"],
                    max_findings=4,
                )
                _assert(
                    await _research_step_count(run_id) == step_count_before,
                    "python analysis should not write research steps",
                )
                _assert(
                    await _evidence_count(run_id) == evidence_count_before,
                    "python analysis should not write evidence",
                )
                _assert(
                    await _memory_event_count(user_id) == memory_count_before,
                    "python analysis should not write memory",
                )

                findings = analysis["findings"]
                collection = await _collect_sources(
                    user_id=str(user_id),
                    run_id=run_id,
                    query=analysis["query"],
                    sources=findings,
                    subquestion=analysis["subquestion"],
                    provider_source="python_analysis",
                )
                first_finding = findings[0]
                await _add_evidence(
                    user_id=str(user_id),
                    run_id=run_id,
                    source_type=first_finding["source_type"],
                    source_title=first_finding["source_title"],
                    source_url=first_finding["source_url"],
                    claim=first_finding["claim"],
                    excerpt=first_finding["excerpt"],
                    quality=first_finding["quality"],
                    relevance=first_finding["relevance"],
                    known_facts=[first_finding["claim"]],
                )
                final_answer = await _finalize_answer(
                    user_id=str(user_id),
                    run_id=run_id,
                )

        _assert(analysis["result_mode"] == "research_python_analysis", str(analysis))
        _assert(
            analysis["contract_version"] == "research-python-analysis-v1",
            str(analysis),
        )
        _assert(analysis["status"] == "ok", str(analysis))
        _assert(analysis["record_count"] == 3, str(analysis))
        _assert(analysis["analyzed_record_count"] == 3, str(analysis))
        _assert(analysis["finding_count"] >= 2, str(analysis))
        _assert(VERIFIED_CLAIM_FRAGMENT in analysis["findings"][0]["claim"], str(analysis))
        _assert(
            analysis["metadata"]["writes_research_state"] is False,
            str(analysis["metadata"]),
        )
        _assert(analysis["metadata"]["external_call"] is False, str(analysis["metadata"]))
        _assert(
            analysis["metadata"]["executes_user_code"] is False,
            str(analysis["metadata"]),
        )
        _assert(analysis["metadata"]["reads_files"] is False, str(analysis["metadata"]))
        _assert(analysis["metadata"]["network_access"] is False, str(analysis["metadata"]))
        _assert(
            analysis["observation_batch"]["observation_count"] >= 1,
            str(analysis["observation_batch"]),
        )
        _assert(
            collection["metadata"]["writes_research_state"] is True,
            str(collection["metadata"]),
        )
        _assert(final_answer["answer_status"] == "verified", str(final_answer))
        _assert(VERIFIED_CLAIM_FRAGMENT in final_answer["answer"], final_answer["answer"])
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
        await _run_python_analysis_flow()
    finally:
        await dispose_database()
    print("research python analysis verification passed")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-migration", action="store_true")
    args = parser.parse_args()

    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(_main(skip_migration=args.skip_migration))


if __name__ == "__main__":
    main()
