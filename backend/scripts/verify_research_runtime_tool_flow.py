"""Verify the local Deep Research runtime tool.

This check uses deterministic normalized observations. It verifies:
- run_research_harness is gated by Deep Research intent
- the harness writes research state and evidence, not long-term memory
- the tool returns research-runtime-v1 with a nested research-report-v1
- CurrentMemory is included as report context only
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
from app.services.memory import MemoryCandidate, get_memory_orchestrator
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
            {"user_id": user_id, "display_name": "Research Runtime Verify"},
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
                "title": "Research Runtime Verify",
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


async def _run_runtime_tool(**payload: Any) -> dict[str, Any]:
    return json.loads(await research_tools.run_research_harness.ainvoke(payload))


async def _run_research_runtime_tool_flow() -> None:
    user_id = uuid.uuid4()
    thread_id = uuid.uuid4()

    await _insert_temp_user_and_thread(user_id, thread_id)
    try:
        remembered = await get_memory_orchestrator().remember_candidate(
            MemoryCandidate(
                user_id=user_id,
                thread_id=thread_id,
                type="preference",
                subject="content",
                value="avoid bleak or overly dark books",
                polarity="avoid",
                source_kind="user_message",
                source_text="I avoid bleak or overly dark books.",
            )
        )
        _assert(remembered.memory is not None, "memory setup should be admitted")

        reset_tool_admission_gate()
        with request_id_scope("verify-runtime-tool-blocked"):
            with user_message_scope("What is the style of Nonviolent Communication?"):
                blocked = await _run_runtime_tool(
                    user_id=str(user_id),
                    thread_id=str(thread_id),
                    objective="Research should not run for a style-only question.",
                    observations=[
                        {
                            "source_type": "web",
                            "source_title": "Blocked Source",
                            "source_url": "https://example.test/blocked",
                            "claim": "This claim should not be stored.",
                            "excerpt": "Blocked.",
                            "quality": "medium",
                            "relevance": 4,
                            "metadata": {"provider_source": "verify_seed"},
                        }
                    ],
                )
        _assert(blocked["status"] == "tool_blocked", str(blocked))
        _assert(
            "can_start_research"
            in blocked["tool_admission"]["metadata"]["missing_policy_flags"],
            str(blocked["tool_admission"]),
        )

        memory_count_before = await _memory_event_count(user_id)
        reset_tool_admission_gate()
        with request_id_scope("verify-runtime-tool-allowed"):
            with user_message_scope(
                "Please deep research whether Example Novel fits my constraints."
            ):
                result = await _run_runtime_tool(
                    user_id=str(user_id),
                    thread_id=str(thread_id),
                    objective=(
                        "Assess whether Example Novel fits a warm reading "
                        "request for this user."
                    ),
                    mode="deep_research",
                    subquestions=[
                        "Is Example Novel warm and character-driven?",
                    ],
                    gaps=["Need source-backed evidence."],
                    next_actions=["Run the local research harness."],
                    budget={
                        "max_steps": 7,
                        "max_sources": 2,
                        "required_evidence_quality": "medium",
                    },
                    stop_criteria=[
                        "At least one claim has medium quality evidence.",
                    ],
                    observations=[
                        {
                            "source_type": "web",
                            "source_title": "Reliable Review",
                            "source_url": "https://example.test/reliable-review",
                            "claim": (
                                "Example Novel is warm and character-driven."
                            ),
                            "excerpt": (
                                "The review describes a gentle character-focused "
                                "story."
                            ),
                            "quality": "medium",
                            "relevance": 5,
                            "metadata": {"provider_source": "verify_seed"},
                        }
                    ],
                    metadata={"trace_id": "verify_runtime_tool"},
                )

        _assert(result["result_mode"] == "research_runtime", str(result))
        _assert(result["contract_version"] == "research-runtime-v1", str(result))
        _assert(result["status"] == "completed", str(result))
        _assert(result["metadata"]["provider_mode"] == "source_observations", str(result))
        _assert(result["metadata"]["external_call"] is False, str(result["metadata"]))
        _assert(result["metadata"]["writes_research_state"] is True, str(result))
        _assert(
            result["metadata"]["writes_long_term_memory"] is False,
            str(result["metadata"]),
        )

        report = result["report"]
        _assert(report["result_mode"] == "research_report", str(report))
        _assert(report["contract_version"] == "research-report-v1", str(report))
        _assert(report["report_status"] == "verified", str(report))
        _assert(
            [claim["claim"] for claim in report["verified_claims"]]
            == ["Example Novel is warm and character-driven."],
            str(report["verified_claims"]),
        )
        _assert(
            any(source["source_title"] == "Reliable Review" for source in report["sources"]),
            str(report["sources"]),
        )
        _assert(
            "avoid bleak or overly dark books"
            in " ".join(report["memory_context"]["constraints"]),
            str(report["memory_context"]),
        )

        step_types = await _research_step_types(result["run_id"])
        for expected in ("search", "visit", "add_evidence", "update_state", "finish"):
            _assert(expected in step_types, f"missing research step: {expected}")
        _assert(
            await _memory_event_count(user_id) == memory_count_before,
            "runtime tool should not write long-term memory",
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
        await _run_research_runtime_tool_flow()
    finally:
        await dispose_database()
    print("research runtime tool verification passed")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-migration", action="store_true")
    args = parser.parse_args()

    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(_main(skip_migration=args.skip_migration))


if __name__ == "__main__":
    main()
