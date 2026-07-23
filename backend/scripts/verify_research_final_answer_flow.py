"""Verify read-only Deep Research final-answer projection.

This check avoids live web/LLM calls. It verifies:
- finalize_research_answer is gated by Deep Search / Deep Research intent
- final answers contain verified claims only
- uncertain/rejected claims are returned as omitted records, not final facts
- finalization does not mutate research state, evidence, or long-term memory
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import uuid
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import text

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.agents.tools import research as research_tools
from app.infra.database import dispose_database, get_database, init_database
from app.infra.llm.embedding import init_embedding_model
from app.services.memory import MemoryCandidate, get_memory_orchestrator
from app.services.research import ResearchEvidence, get_research_orchestrator
from app.services.tool_admission import reset_tool_admission_gate
from app.utils.logging import request_id_scope
from app.utils.turn_context import user_message_scope
from scripts.init_database import _init_postgres


VERIFIED_CLAIM = "Example Novel is warm and character-driven."
UNCERTAIN_CLAIM = "Example Novel has no bleak content."


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
            {"user_id": user_id, "display_name": "Research Final Answer Verify"},
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
                "title": "Research Final Answer Verify",
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


async def _research_step_count(run_id: uuid.UUID) -> int:
    db = get_database()
    async with db.session() as session:
        count = await session.scalar(
            text("SELECT COUNT(*) FROM public.research_steps WHERE run_id = :run_id"),
            {"run_id": run_id},
        )
        return int(count or 0)


async def _evidence_count(run_id: uuid.UUID) -> int:
    db = get_database()
    async with db.session() as session:
        count = await session.scalar(
            text(
                "SELECT COUNT(*) FROM public.research_evidence WHERE run_id = :run_id"
            ),
            {"run_id": run_id},
        )
        return int(count or 0)


async def _finalize_answer(**payload: str | int) -> dict:
    return json.loads(await research_tools.finalize_research_answer.ainvoke(payload))


async def _run_research_final_answer_flow() -> None:
    user_id = uuid.uuid4()
    thread_id = uuid.uuid4()
    memory = get_memory_orchestrator()
    research = get_research_orchestrator()

    await _insert_temp_user_and_thread(user_id, thread_id)
    try:
        reset_tool_admission_gate()
        with request_id_scope("verify-research-final-answer-blocked"):
            with user_message_scope("What is the style of Nonviolent Communication?"):
                blocked = await _finalize_answer(
                    user_id=str(user_id),
                    run_id=str(uuid.uuid4()),
                )
        _assert(blocked["status"] == "tool_blocked", str(blocked))
        _assert(blocked["result_mode"] == "research_final_answer", str(blocked))
        _assert(blocked["answer_status"] == "tool_blocked", str(blocked))
        _assert(
            "can_use_research_tools"
            in blocked["metadata"]["tool_admission"]["metadata"][
                "missing_policy_flags"
            ],
            str(blocked["metadata"]["tool_admission"]),
        )

        remembered = await memory.remember_candidate(
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

        started = await research.start_research(
            user_id=user_id,
            thread_id=thread_id,
            objective="Assess whether Example Novel fits a warm reading request.",
            mode="deep_research",
            subquestions=["Is Example Novel warm and character-driven?"],
            gaps=[],
            next_actions=["Collect source-backed evidence."],
            budget={"required_evidence_quality": "medium"},
            stop_criteria=["At least one claim has medium quality evidence."],
        )
        run_id = started.run.id
        _assert(run_id is not None, "run id should exist")
        assert run_id is not None

        await research.add_evidence(
            user_id=user_id,
            run_id=run_id,
            evidence=ResearchEvidence(
                run_id=run_id,
                source_type="web",
                source_title="Reliable Review",
                source_url="https://example.test/reliable-review",
                claim=VERIFIED_CLAIM,
                excerpt="The review describes a gentle character-focused story.",
                quality="medium",
                relevance=5,
            ),
            known_facts=[VERIFIED_CLAIM],
            next_actions=["Check content risk."],
        )
        await research.add_evidence(
            user_id=user_id,
            run_id=run_id,
            evidence=ResearchEvidence(
                run_id=run_id,
                source_type="web",
                source_title="Weak Forum Note",
                source_url="https://example.test/weak-forum-note",
                claim=UNCERTAIN_CLAIM,
                excerpt="A weak forum note says the book does not become bleak.",
                quality="low",
                relevance=3,
            ),
            known_facts=["Weak note suggests no bleak content."],
            next_actions=["Finalize answer with uncertainty separated."],
        )

        memory_count_before = await _memory_event_count(user_id)
        step_count_before = await _research_step_count(run_id)
        evidence_count_before = await _evidence_count(run_id)

        reset_tool_admission_gate()
        with request_id_scope("verify-research-final-answer"):
            with user_message_scope(
                "Please deep research Example Novel and give me the final answer."
            ):
                final_answer = await _finalize_answer(
                    user_id=str(user_id),
                    run_id=str(run_id),
                    limit_steps=100,
                    limit_evidence=100,
                )

        _assert(
            final_answer["result_mode"] == "research_final_answer",
            str(final_answer),
        )
        _assert(
            final_answer["contract_version"] == "research-final-answer-v1",
            str(final_answer),
        )
        _assert(final_answer["report_status"] == "verified", str(final_answer))
        _assert(final_answer["answer_status"] == "verified", str(final_answer))
        _assert(final_answer["ready_for_final_answer"] is True, str(final_answer))
        _assert(
            [claim["claim"] for claim in final_answer["verified_claims"]]
            == [VERIFIED_CLAIM],
            str(final_answer["verified_claims"]),
        )
        _assert(VERIFIED_CLAIM in final_answer["answer"], final_answer["answer"])
        _assert(
            UNCERTAIN_CLAIM not in final_answer["answer"],
            "uncertain claim text must not become a final fact",
        )
        _assert(
            [claim["claim"] for claim in final_answer["omitted_uncertain_claims"]]
            == [UNCERTAIN_CLAIM],
            str(final_answer["omitted_uncertain_claims"]),
        )
        _assert(
            any(
                "uncertain claim" in limitation
                for limitation in final_answer["limitations"]
            ),
            str(final_answer["limitations"]),
        )
        _assert(
            [source["source_title"] for source in final_answer["sources"]]
            == ["Reliable Review"],
            str(final_answer["sources"]),
        )
        _assert(
            final_answer["metadata"]["writes_research_state"] is False,
            str(final_answer["metadata"]),
        )
        _assert(
            final_answer["metadata"]["writes_long_term_memory"] is False,
            str(final_answer["metadata"]),
        )
        _assert(
            final_answer["metadata"]["external_call"] is False,
            str(final_answer["metadata"]),
        )
        _assert(
            await _memory_event_count(user_id) == memory_count_before,
            "final answer projection should not write memory",
        )
        _assert(
            await _research_step_count(run_id) == step_count_before,
            "final answer projection should not write research steps",
        )
        _assert(
            await _evidence_count(run_id) == evidence_count_before,
            "final answer projection should not write evidence",
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
        await _run_research_final_answer_flow()
    finally:
        await dispose_database()
    print("research final answer verification passed")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-migration", action="store_true")
    args = parser.parse_args()

    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(_main(skip_migration=args.skip_migration))


if __name__ == "__main__":
    main()
