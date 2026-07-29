"""Verify controlled research source search.

This check avoids live network calls by monkeypatching the search provider. It
verifies:
- search_research_sources is gated by Deep Search / Deep Research intent
- provider documents become research-source-search-v1 plus nested extraction
- source search is read-only for app state
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
import app.services.research.source_search as source_search_service
from app.services.research import ResearchSourceDocument, ResearchSourceSearchProviderResult
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
            {"user_id": user_id, "display_name": "Research Source Search Verify"},
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
                "title": "Research Source Search Verify",
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


async def _search_sources(**payload: Any) -> dict[str, Any]:
    return json.loads(await research_tools.search_research_sources.ainvoke(payload))


async def _collect_sources(**payload: Any) -> dict[str, Any]:
    return json.loads(await research_tools.collect_research_sources.ainvoke(payload))


async def _add_evidence(**payload: Any) -> dict[str, Any]:
    return json.loads(await research_tools.add_evidence.ainvoke(payload))


async def _finalize_answer(**payload: Any) -> dict[str, Any]:
    return json.loads(await research_tools.finalize_research_answer.ainvoke(payload))


async def _run_source_search_flow() -> None:
    user_id = uuid.uuid4()
    thread_id = uuid.uuid4()
    provider_call_count = 0
    original_provider = source_search_service.search_external_research_documents

    async def fake_duckduckgo_search(
        *,
        query: str,
        subquestion: str = "",
        limit: int = 5,
        provider_query: str = "",
    ) -> ResearchSourceSearchProviderResult:
        nonlocal provider_call_count
        provider_call_count += 1
        return ResearchSourceSearchProviderResult(
            provider_name="duckduckgo",
            provider_query=provider_query or f"{query} {subquestion}".strip(),
            status="ok",
            documents=[
                ResearchSourceDocument(
                    source_type="web",
                    source_title="Reliable Review",
                    source_url="https://example.test/reliable-review",
                    content=(
                        f"{VERIFIED_CLAIM} The review says the story is gentle "
                        "and focused on character relationships."
                    ),
                    quality="medium",
                    relevance=5,
                    metadata={
                        "provider_source": "duckduckgo",
                        "provider_raw": {"kind": "fake_search_result", "rank": 1},
                    },
                ),
                ResearchSourceDocument(
                    source_type="web",
                    source_title="Unrelated Result",
                    source_url="https://example.test/unrelated",
                    content="This unrelated result discusses a different topic.",
                    quality="medium",
                    relevance=1,
                    metadata={
                        "provider_source": "duckduckgo",
                        "provider_raw": {"kind": "fake_search_result", "rank": 2},
                    },
                ),
            ][:limit],
            duration_ms=1,
            metadata={"provider_source": "duckduckgo", "fake": True},
        )

    source_search_service.search_external_research_documents = fake_duckduckgo_search
    await _insert_temp_user_and_thread(user_id, thread_id)
    try:
        reset_tool_admission_gate()
        with request_id_scope("verify-source-search-blocked"):
            with user_message_scope("What is the style of Nonviolent Communication?"):
                blocked = await _search_sources(query="Example Novel review", limit=3)
        _assert(blocked["status"] == "tool_blocked", str(blocked))
        _assert(blocked["result_mode"] == "research_source_search", str(blocked))
        _assert(provider_call_count == 0, "blocked tool called provider")

        reset_tool_admission_gate()
        with request_id_scope("verify-source-search-flow"):
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
                    next_actions=["Search source-backed reviews."],
                    budget={"required_evidence_quality": "medium"},
                    stop_criteria=["One medium-quality source-backed claim."],
                )
                run_id = started["run"]["id"]
                memory_count_before = await _memory_event_count(user_id)
                step_count_before = await _research_step_count(run_id)
                evidence_count_before = await _evidence_count(run_id)

                source_search = await _search_sources(
                    query="Example Novel warm character-driven review",
                    subquestion="Is Example Novel warm and character-driven?",
                    limit=5,
                )
                _assert(
                    await _research_step_count(run_id) == step_count_before,
                    "source search should not write research steps",
                )
                _assert(
                    await _evidence_count(run_id) == evidence_count_before,
                    "source search should not write evidence",
                )
                _assert(
                    await _memory_event_count(user_id) == memory_count_before,
                    "source search should not write memory",
                )

                records = source_search["extraction"]["source_records"]
                collection = await _collect_sources(
                    user_id=str(user_id),
                    run_id=run_id,
                    query=source_search["query"],
                    sources=records,
                    subquestion=source_search["subquestion"],
                    provider_source="duckduckgo_source_search",
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
                    quality=first_record["quality"],
                    relevance=first_record["relevance"],
                    known_facts=[first_record["claim"]],
                )
                final_answer = await _finalize_answer(
                    user_id=str(user_id),
                    run_id=run_id,
                )

        _assert(source_search["result_mode"] == "research_source_search", str(source_search))
        _assert(
            source_search["contract_version"] == "research-source-search-v1",
            str(source_search),
        )
        _assert(source_search["status"] == "ok", str(source_search))
        _assert(source_search["document_count"] == 2, str(source_search))
        _assert(source_search["extracted_count"] >= 1, str(source_search))
        _assert(
            source_search["metadata"]["external_call"] is True,
            str(source_search["metadata"]),
        )
        _assert(
            source_search["metadata"]["writes_research_state"] is False,
            str(source_search["metadata"]),
        )
        _assert(
            source_search["extraction"]["metadata"]["external_call"] is False,
            str(source_search["extraction"]["metadata"]),
        )
        _assert(
            collection["metadata"]["writes_research_state"] is True,
            str(collection["metadata"]),
        )
        _assert(final_answer["answer_status"] == "verified", str(final_answer))
        _assert(VERIFIED_CLAIM in final_answer["answer"], final_answer["answer"])
    finally:
        source_search_service.search_external_research_documents = original_provider
        await _delete_temp_user(user_id)
        reset_tool_admission_gate()


async def _main(skip_migration: bool) -> None:
    load_dotenv()
    if not skip_migration:
        _init_postgres()
    init_embedding_model()
    await init_database()
    try:
        await _run_source_search_flow()
    finally:
        await dispose_database()
    print("research source search verification passed")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-migration", action="store_true")
    args = parser.parse_args()

    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(_main(skip_migration=args.skip_migration))


if __name__ == "__main__":
    main()
