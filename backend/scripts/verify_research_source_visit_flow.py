"""Verify controlled research source visit/fetch.

This check avoids live network calls by monkeypatching URL fetch. It verifies:
- fetch_research_source is gated by Deep Search / Deep Research intent
- approved URL content becomes research-source-visit-v1 plus nested extraction
- source visit/fetch is read-only for app state
- extracted records can flow through collection, evidence admission, report,
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
import app.services.research.source_visit as source_visit_service
from app.services.tool_admission import reset_tool_admission_gate
from app.utils.logging import request_id_scope
from app.utils.turn_context import user_message_scope
from scripts.init_database import _init_postgres


VERIFIED_CLAIM = "Example Novel is warm and character-driven."


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
            {"user_id": user_id, "display_name": "Research Source Visit Verify"},
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
                "title": "Research Source Visit Verify",
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


async def _fetch_source(**payload: Any) -> dict[str, Any]:
    return json.loads(await research_tools.fetch_research_source.ainvoke(payload))


async def _collect_sources(**payload: Any) -> dict[str, Any]:
    return json.loads(await research_tools.collect_research_sources.ainvoke(payload))


async def _add_evidence(**payload: Any) -> dict[str, Any]:
    return json.loads(await research_tools.add_evidence.ainvoke(payload))


async def _finalize_answer(**payload: Any) -> dict[str, Any]:
    return json.loads(await research_tools.finalize_research_answer.ainvoke(payload))


async def _run_source_visit_flow() -> None:
    user_id = uuid.uuid4()
    thread_id = uuid.uuid4()
    fetch_call_count = 0
    original_fetch = source_visit_service._fetch_url

    async def fake_fetch_url(url: str, *, timeout_seconds: int) -> dict[str, Any]:
        nonlocal fetch_call_count
        fetch_call_count += 1
        return {
            "status": "ok",
            "body": (
                "<html><head><title>Reliable Review</title></head><body>"
                f"<p>{VERIFIED_CLAIM} The review says the story is gentle "
                "and focused on character relationships.</p>"
                "</body></html>"
            ),
            "status_code": 200,
            "final_url": url,
            "content_type": "text/html; charset=utf-8",
            "byte_count": 200,
            "truncated": False,
        }

    source_visit_service._fetch_url = fake_fetch_url
    await _insert_temp_user_and_thread(user_id, thread_id)
    try:
        reset_tool_admission_gate()
        with request_id_scope("verify-source-visit-blocked"):
            with user_message_scope("What is the style of Nonviolent Communication?"):
                blocked = await _fetch_source(
                    url="https://example.test/reliable-review",
                    query="Example Novel review",
                )
        _assert(blocked["status"] == "tool_blocked", str(blocked))
        _assert(blocked["result_mode"] == "research_source_visit", str(blocked))
        _assert(fetch_call_count == 0, "blocked tool called fetch provider")

        reset_tool_admission_gate()
        with request_id_scope("verify-source-visit-private-url-blocked"):
            with user_message_scope("Please deep research Example Novel."):
                private_blocked = await _fetch_source(
                    url="http://127.0.0.1:5433/internal",
                    query="Example Novel review",
                )
        _assert(private_blocked["status"] == "blocked_url", str(private_blocked))
        _assert(
            private_blocked["metadata"]["external_call"] is False,
            str(private_blocked["metadata"]),
        )
        _assert(fetch_call_count == 0, "blocked private URL called fetch provider")

        reset_tool_admission_gate()
        with request_id_scope("verify-source-visit-flow"):
            with user_message_scope(
                "Please deep research whether Example Novel is warm."
            ):
                started = await _start_research(
                    user_id=str(user_id),
                    thread_id=str(thread_id),
                    objective="Assess whether Example Novel fits a warm request.",
                    mode="deep_research",
                    subquestions=["Is Example Novel warm and character-driven?"],
                    gaps=[],
                    next_actions=["Fetch source-backed reviews."],
                    budget={"required_evidence_quality": "medium"},
                    stop_criteria=["One medium-quality source-backed claim."],
                )
                run_id = started["run"]["id"]
                memory_count_before = await _memory_event_count(user_id)
                step_count_before = await _research_step_count(run_id)
                evidence_count_before = await _evidence_count(run_id)

                source_visit = await _fetch_source(
                    url="https://example.test/reliable-review",
                    query="Example Novel warm character-driven review",
                    subquestion="Is Example Novel warm and character-driven?",
                )
                _assert(
                    await _research_step_count(run_id) == step_count_before,
                    "source visit should not write research steps",
                )
                _assert(
                    await _evidence_count(run_id) == evidence_count_before,
                    "source visit should not write evidence",
                )
                _assert(
                    await _memory_event_count(user_id) == memory_count_before,
                    "source visit should not write memory",
                )

                records = source_visit["extraction"]["source_records"]
                collection = await _collect_sources(
                    user_id=str(user_id),
                    run_id=run_id,
                    query=source_visit["query"],
                    sources=records,
                    subquestion=source_visit["subquestion"],
                    provider_source="source_visit",
                )
                first_record = records[0]
                await _add_evidence(
                    user_id=str(user_id),
                    run_id=run_id,
                    source_type=first_record["source_type"],
                    source_title=first_record["source_title"],
                    source_url=first_record["source_url"],
                    claim=first_record["claim"],
                    excerpt=first_record["excerpt"],
                    quality="medium",
                    relevance=first_record["relevance"],
                    known_facts=[first_record["claim"]],
                )
                final_answer = await _finalize_answer(
                    user_id=str(user_id),
                    run_id=run_id,
                )

        _assert(source_visit["result_mode"] == "research_source_visit", str(source_visit))
        _assert(
            source_visit["contract_version"] == "research-source-visit-v1",
            str(source_visit),
        )
        _assert(source_visit["status"] == "ok", str(source_visit))
        _assert(
            source_visit["source_document"]["source_title"] == "Reliable Review",
            str(source_visit["source_document"]),
        )
        _assert(source_visit["extracted_count"] >= 1, str(source_visit))
        _assert(
            source_visit["metadata"]["external_call"] is True,
            str(source_visit["metadata"]),
        )
        _assert(
            source_visit["metadata"]["writes_research_state"] is False,
            str(source_visit["metadata"]),
        )
        _assert(
            source_visit["extraction"]["metadata"]["external_call"] is False,
            str(source_visit["extraction"]["metadata"]),
        )
        _assert(
            collection["metadata"]["writes_research_state"] is True,
            str(collection["metadata"]),
        )
        _assert(final_answer["answer_status"] == "verified", str(final_answer))
        _assert(VERIFIED_CLAIM in final_answer["answer"], final_answer["answer"])
    finally:
        source_visit_service._fetch_url = original_fetch
        await _delete_temp_user(user_id)
        reset_tool_admission_gate()


async def _main(skip_migration: bool) -> None:
    load_dotenv()
    if not skip_migration:
        _init_postgres()
    init_embedding_model()
    await init_database()
    try:
        await _run_source_visit_flow()
    finally:
        await dispose_database()
    print("research source visit verification passed")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-migration", action="store_true")
    args = parser.parse_args()

    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(_main(skip_migration=args.skip_migration))


if __name__ == "__main__":
    main()
