"""Verify research source acquisition normalization.

This check avoids live web/provider calls. It verifies:
- build_research_observations is gated by research intent
- source records normalize into app-owned ResearchObservation objects
- records without claim/excerpt/source metadata are rejected
- normalized observations can feed run_research_harness and produce a report
- normalization itself writes no memory or research state
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
            {"user_id": user_id, "display_name": "Research Observation Verify"},
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
                "title": "Research Observation Verify",
            },
        )


async def _delete_temp_user(user_id: uuid.UUID) -> None:
    db = get_database()
    async with db.session() as session:
        await session.execute(
            text("DELETE FROM public.users WHERE id = :user_id"),
            {"user_id": user_id},
        )


async def _count_rows(table: str, user_id: uuid.UUID) -> int:
    db = get_database()
    async with db.session() as session:
        count = await session.scalar(
            text(f"SELECT COUNT(*) FROM public.{table} WHERE user_id = :user_id"),
            {"user_id": user_id},
        )
        return int(count or 0)


async def _build_observations(**payload: Any) -> dict[str, Any]:
    return json.loads(await research_tools.build_research_observations.ainvoke(payload))


async def _run_runtime(**payload: Any) -> dict[str, Any]:
    return json.loads(await research_tools.run_research_harness.ainvoke(payload))


async def _run_observation_batch_flow() -> None:
    user_id = uuid.uuid4()
    thread_id = uuid.uuid4()

    await _insert_temp_user_and_thread(user_id, thread_id)
    try:
        reset_tool_admission_gate()
        with request_id_scope("verify-observation-batch-blocked"):
            with user_message_scope("What is the style of Nonviolent Communication?"):
                blocked = await _build_observations(
                    query="style question",
                    sources=[
                        {
                            "title": "Blocked Source",
                            "url": "https://example.test/blocked",
                            "claim": "This should not normalize outside research intent.",
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

        memory_count_before = await _count_rows("memory_events", user_id)
        run_count_before = await _count_rows("research_runs", user_id)
        reset_tool_admission_gate()
        with request_id_scope("verify-observation-batch-allowed"):
            with user_message_scope(
                "Please deep research whether Example Novel fits this reading request."
            ):
                batch = await _build_observations(
                    query="Example Novel warm character-driven review",
                    subquestion="Is Example Novel warm and character-driven?",
                    provider_source="verify_source_tool",
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
                            "score": 0.94,
                            "metadata": {"source_kind": "fixture"},
                        },
                        {
                            "title": "No Claim Source",
                            "url": "https://example.test/no-claim",
                            "content": "This source has an excerpt but no claim.",
                        },
                        {
                            "title": "No Excerpt Source",
                            "url": "https://example.test/no-excerpt",
                            "claim": "This source has a claim but no excerpt.",
                        },
                    ],
                    metadata={"trace_id": "verify_observation_batch"},
                )

                _assert(batch["result_mode"] == "research_observation_batch", str(batch))
                _assert(
                    batch["contract_version"] == "research-observation-batch-v1",
                    str(batch),
                )
                _assert(batch["status"] == "ok", str(batch))
                _assert(batch["source_count"] == 3, str(batch))
                _assert(batch["observation_count"] == 1, str(batch))
                _assert(len(batch["rejected_sources"]) == 2, str(batch))
                rejected_reasons = {
                    reason
                    for item in batch["rejected_sources"]
                    for reason in item["reason_codes"]
                }
                _assert("missing_claim" in rejected_reasons, str(batch))
                _assert("missing_excerpt" in rejected_reasons, str(batch))
                _assert(batch["metadata"]["external_call"] is False, str(batch))
                _assert(
                    batch["metadata"]["writes_research_state"] is False,
                    str(batch),
                )
                _assert(
                    await _count_rows("memory_events", user_id) == memory_count_before,
                    "observation normalization should not write memory",
                )
                _assert(
                    await _count_rows("research_runs", user_id) == run_count_before,
                    "observation normalization should not write research state",
                )

                observation = batch["observations"][0]
                _assert(
                    observation["metadata"]["provider_source"] == "verify_source_tool",
                    str(observation),
                )
                _assert(
                    observation["metadata"]["provider_raw"]["title"] == "Reliable Review",
                    str(observation),
                )

                runtime = await _run_runtime(
                    user_id=str(user_id),
                    thread_id=str(thread_id),
                    objective="Assess Example Novel from normalized observations.",
                    mode="deep_research",
                    subquestions=["Is Example Novel warm and character-driven?"],
                    budget={"required_evidence_quality": "medium"},
                    stop_criteria=["One medium-quality claim is admitted."],
                    observations=batch["observations"],
                )

        _assert(runtime["result_mode"] == "research_runtime", str(runtime))
        _assert(runtime["report"]["result_mode"] == "research_report", str(runtime))
        _assert(runtime["report"]["report_status"] == "verified", str(runtime))
        _assert(
            runtime["report"]["verified_claims"][0]["claim"]
            == "Example Novel is warm and character-driven.",
            str(runtime["report"]["verified_claims"]),
        )
        _assert(
            runtime["report"]["sources"][0]["source_title"] == "Reliable Review",
            str(runtime["report"]["sources"]),
        )
        _assert(
            await _count_rows("memory_events", user_id) == memory_count_before,
            "runtime fed by observations should not write memory",
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
        await _run_observation_batch_flow()
    finally:
        await dispose_database()
    print("research observation batch verification passed")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-migration", action="store_true")
    args = parser.parse_args()

    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(_main(skip_migration=args.skip_migration))


if __name__ == "__main__":
    main()
