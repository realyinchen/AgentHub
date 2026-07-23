"""Verify Research Evidence Admission Gate.

This check avoids live web/provider calls. It verifies:
- add_evidence remains gated by Deep Search / Deep Research intent
- incomplete source material is rejected before Evidence Store insertion
- low-quality but traceable evidence is stored with admission warnings
- report projection keeps low-quality claims uncertain
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
            {"user_id": user_id, "display_name": "Evidence Admission Verify"},
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
                "title": "Evidence Admission Verify",
            },
        )


async def _delete_temp_user(user_id: uuid.UUID) -> None:
    db = get_database()
    async with db.session() as session:
        await session.execute(
            text("DELETE FROM public.users WHERE id = :user_id"),
            {"user_id": user_id},
        )


async def _evidence_count(run_id: str) -> int:
    db = get_database()
    async with db.session() as session:
        count = await session.scalar(
            text("SELECT COUNT(*) FROM public.research_evidence WHERE run_id = :run_id"),
            {"run_id": run_id},
        )
        return int(count or 0)


async def _latest_add_evidence_step(run_id: str) -> dict[str, Any]:
    db = get_database()
    async with db.session() as session:
        row = (
            await session.execute(
                text(
                    """
                    SELECT status, output, error
                    FROM public.research_steps
                    WHERE run_id = :run_id AND step_type = 'add_evidence'
                    ORDER BY created_at DESC
                    LIMIT 1
                    """
                ),
                {"run_id": run_id},
            )
        ).one()
        return {
            "status": str(row[0]),
            "output": row[1] or {},
            "error": row[2],
        }


async def _start_research(**payload: Any) -> dict[str, Any]:
    return json.loads(await research_tools.start_research.ainvoke(payload))


async def _add_evidence(**payload: Any) -> dict[str, Any]:
    return json.loads(await research_tools.add_evidence.ainvoke(payload))


async def _build_report(**payload: Any) -> dict[str, Any]:
    return json.loads(await research_tools.build_research_report.ainvoke(payload))


async def _run_evidence_admission_flow() -> None:
    user_id = uuid.uuid4()
    thread_id = uuid.uuid4()

    await _insert_temp_user_and_thread(user_id, thread_id)
    try:
        reset_tool_admission_gate()
        with request_id_scope("verify-evidence-admission-blocked"):
            with user_message_scope("What is a cozy novel?"):
                blocked = await _add_evidence(
                    user_id=str(user_id),
                    run_id=str(uuid.uuid4()),
                    claim="This should be blocked outside research intent.",
                    source_title="Blocked Source",
                    source_url="https://example.test/blocked",
                    excerpt="Blocked.",
                    quality="medium",
                    relevance=5,
                )
        _assert(blocked["status"] == "tool_blocked", str(blocked))

        reset_tool_admission_gate()
        with request_id_scope("verify-evidence-admission"):
            with user_message_scope("Please deep research Example Novel fit."):
                started = await _start_research(
                    user_id=str(user_id),
                    thread_id=str(thread_id),
                    objective="Assess Example Novel with evidence admission.",
                    mode="deep_research",
                    subquestions=["Is Example Novel warm?"],
                    gaps=[],
                    next_actions=["Admit source-backed evidence."],
                    budget={"required_evidence_quality": "medium"},
                    stop_criteria=["Admit only source-backed evidence."],
                )
                run_id = started["run"]["id"]

                rejected_state = await _add_evidence(
                    user_id=str(user_id),
                    run_id=run_id,
                    source_type="web",
                    source_title="Incomplete Review",
                    source_url="https://example.test/incomplete-review",
                    claim="Example Novel is warm.",
                    excerpt="",
                    quality="medium",
                    relevance=5,
                    next_actions=["Collect a source excerpt before retrying."],
                )
                _assert(rejected_state["evidence"] == [], str(rejected_state["evidence"]))
                _assert(await _evidence_count(run_id) == 0, "rejected evidence entered DB")
                rejected_step = await _latest_add_evidence_step(run_id)
                _assert(rejected_step["status"] == "skipped", str(rejected_step))
                rejected_admission = rejected_step["output"]["evidence_admission"]
                _assert(rejected_admission["allowed"] is False, str(rejected_admission))
                _assert(
                    "missing_excerpt" in rejected_admission["reason_codes"],
                    str(rejected_admission),
                )

                accepted_state = await _add_evidence(
                    user_id=str(user_id),
                    run_id=run_id,
                    source_type="web",
                    source_title="Weak Review",
                    source_url="https://example.test/weak-review",
                    claim="Example Novel may be warm.",
                    excerpt="A weak review says readers may find the tone warm.",
                    quality="low",
                    relevance=2,
                    known_facts=["Example Novel may be warm."],
                    next_actions=["Build report and keep quality uncertainty visible."],
                )
                _assert(await _evidence_count(run_id) == 1, "accepted evidence missing")
                _assert(len(accepted_state["evidence"]) == 1, str(accepted_state["evidence"]))
                evidence_metadata = accepted_state["evidence"][0]["metadata"]
                admission = evidence_metadata["evidence_admission"]
                _assert(admission["allowed"] is True, str(admission))
                _assert(
                    {
                        "low_quality_evidence",
                        "low_relevance_evidence",
                    }
                    <= set(admission["warning_codes"]),
                    str(admission),
                )

                report = await _build_report(user_id=str(user_id), run_id=run_id)
                _assert(report["result_mode"] == "research_report", str(report))
                _assert(
                    report["uncertain_claims"]
                    and report["uncertain_claims"][0]["claim"]
                    == "Example Novel may be warm.",
                    str(report),
                )
                _assert(report["verified_claims"] == [], str(report["verified_claims"]))
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
        await _run_evidence_admission_flow()
    finally:
        await dispose_database()
    print("research evidence admission verification passed")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-migration", action="store_true")
    args = parser.parse_args()

    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(_main(skip_migration=args.skip_migration))


if __name__ == "__main__":
    main()
