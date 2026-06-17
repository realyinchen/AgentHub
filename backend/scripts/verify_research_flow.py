"""
Verify the app-owned ResearchOrchestrator contract against local PostgreSQL.

This Phase D check verifies structured research state, not live web search.

Usage:
    cd backend
    .\\.venv\\Scripts\\python.exe scripts\\verify_research_flow.py
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
from app.services.research import get_research_orchestrator
from scripts.init_database import _init_postgres


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def _step_types(result: dict[str, Any]) -> list[str]:
    return [step["step_type"] for step in result["steps"]]


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
            {"user_id": user_id, "display_name": "Research Verify"},
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
                "title": "Research Verify",
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


async def _start(**payload: Any) -> dict[str, Any]:
    return json.loads(await research_tools.start_research.ainvoke(payload))


async def _inspect(**payload: Any) -> dict[str, Any]:
    return json.loads(await research_tools.inspect_research_state.ainvoke(payload))


async def _search(**payload: Any) -> dict[str, Any]:
    return json.loads(await research_tools.search_research.ainvoke(payload))


async def _visit(**payload: Any) -> dict[str, Any]:
    return json.loads(await research_tools.visit_source.ainvoke(payload))


async def _add_evidence(**payload: Any) -> dict[str, Any]:
    return json.loads(await research_tools.add_evidence.ainvoke(payload))


async def _update(**payload: Any) -> dict[str, Any]:
    return json.loads(await research_tools.update_research_state.ainvoke(payload))


async def _finish(**payload: Any) -> dict[str, Any]:
    return json.loads(await research_tools.finish_research.ainvoke(payload))


async def _run_research_flow() -> None:
    user_id = uuid.uuid4()
    thread_id = uuid.uuid4()
    orchestrator = get_research_orchestrator()

    await _insert_temp_user_and_thread(user_id, thread_id)
    try:
        before_memory_count = await _memory_event_count(user_id)

        started = await _start(
            user_id=str(user_id),
            thread_id=str(thread_id),
            objective="Find warm, character-driven recent novels suitable for a reader avoiding bloody content.",
            subquestions=[
                "Which candidate books are warm and character-driven?",
                "Which candidates avoid bloody or very dark content?",
            ],
            gaps=["Need source-backed candidate list."],
            next_actions=["Search for recent warm character-driven novels."],
            budget={"max_steps": 6, "max_sources": 4},
            stop_criteria=[
                "At least two candidate books have evidence.",
                "Known content risks are recorded.",
            ],
        )
        run_id = started["run"]["id"]
        _assert(started["run"]["status"] == "active", "research run should start active")
        _assert(started["state"]["status"] == "active", "state should start active")
        _assert("plan" in _step_types(started), "start should create a plan step")
        _assert(
            "Need source-backed candidate list." in started["state"]["gaps"],
            "initial gap should be in state",
        )

        searched = await _search(
            user_id=str(user_id),
            run_id=run_id,
            query="recent warm character driven novels not dark",
            status="empty_result",
            rationale="Initial broad query did not return usable candidates.",
            results=[],
            next_actions=["Try a narrower source-specific search."],
            duration_ms=12,
        )
        _assert(
            "recent warm character driven novels not dark"
            in searched["state"]["exhausted_queries"],
            "search query should be tracked as exhausted",
        )
        _assert(
            "Try a narrower source-specific search."
            in searched["state"]["next_actions"],
            "search should update next actions",
        )
        _assert("search" in _step_types(searched), "search step should be recorded")

        visited = await _visit(
            user_id=str(user_id),
            run_id=run_id,
            url="https://example.test/source",
            title="Example source",
            summary="Source describes a gentle, character-driven novel.",
            rationale="Check whether candidate tone matches the user constraints.",
            duration_ms=8,
        )
        _assert("visit" in _step_types(visited), "visit step should be recorded")

        evidenced = await _add_evidence(
            user_id=str(user_id),
            run_id=run_id,
            source_type="web",
            source_title="Example source",
            source_url="https://example.test/source",
            claim="Example Novel is described as gentle and character-driven.",
            excerpt="A gentle story focused on relationships and interior change.",
            quality="medium",
            relevance=4,
            known_facts=["Example Novel is gentle and character-driven."],
            gaps=["Need a second independent candidate."],
            next_actions=["Find another candidate with a clearer content warning."],
        )
        _assert(
            len(evidenced["evidence"]) == 1,
            "one evidence item should be stored in research evidence",
        )
        evidence_id = evidenced["evidence"][0]["id"]
        _assert(
            evidence_id in evidenced["state"]["evidence_ids"],
            "state should reference evidence id",
        )
        _assert(
            "Example Novel is gentle and character-driven."
            in evidenced["state"]["known_facts"],
            "known facts should include evidence-derived fact",
        )

        updated = await _update(
            user_id=str(user_id),
            run_id=run_id,
            conflicts=["No conflict found yet."],
            exhausted_queries=["site:example.test bloody content Example Novel"],
            next_actions=["Stop if no second source is available within budget."],
            metadata={"trace_id": "phase_d_verify"},
        )
        _assert(
            "No conflict found yet." in updated["state"]["conflicts"],
            "manual state update should merge conflicts",
        )
        _assert(
            "site:example.test bloody content Example Novel"
            in updated["state"]["exhausted_queries"],
            "manual state update should track exhausted queries",
        )

        finished = await _finish(
            user_id=str(user_id),
            run_id=run_id,
            conclusion="Enough evidence exists for a preliminary recommendation; remaining gap is a second source.",
            known_facts=["Research ended with one supported candidate."],
            gaps=["Second independent source still missing."],
        )
        _assert(
            finished["run"]["status"] == "completed",
            "finished run should be completed",
        )
        _assert(
            finished["state"]["status"] == "completed",
            "latest state snapshot should be completed",
        )
        _assert("finish" in _step_types(finished), "finish step should be recorded")
        _assert(
            finished["state"]["next_actions"] == [],
            "finish should clear next actions",
        )

        inspected = await _inspect(
            user_id=str(user_id),
            run_id=run_id,
            limit_steps=20,
            limit_evidence=20,
        )
        _assert(
            inspected["state"]["status"] == "completed",
            "inspect should return the final completed state",
        )
        _assert(
            len(inspected["steps"]) >= 6,
            "inspect should return the recorded research steps",
        )

        runs = await orchestrator.list_research_runs(
            user_id=user_id,
            status="completed",
            limit=10,
        )
        _assert(
            any(str(run.id) == run_id for run in runs.runs),
            "completed run should appear in completed run list",
        )

        try:
            await _update(
                user_id=str(user_id),
                run_id=run_id,
                gaps=["This should fail because the run is finished."],
            )
        except Exception:
            pass
        else:
            raise AssertionError("finished research runs should not accept updates")

        after_memory_count = await _memory_event_count(user_id)
        _assert(
            before_memory_count == after_memory_count == 0,
            "research state must not write long-term memory events",
        )

        print("research flow verification passed")
        print(f"user_id={user_id}")
        print(f"thread_id={thread_id}")
        print(f"run_id={run_id}")
        print(f"evidence_id={evidence_id}")
    finally:
        await _delete_temp_user(user_id)


async def _main(skip_migration: bool) -> None:
    load_dotenv()
    if not skip_migration:
        _init_postgres()
    init_embedding_model()
    await init_database()
    try:
        await _run_research_flow()
    finally:
        await dispose_database()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--skip-migration",
        action="store_true",
        help="Skip SQL migration and only run behavior checks.",
    )
    args = parser.parse_args()

    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(_main(skip_migration=args.skip_migration))


if __name__ == "__main__":
    main()
