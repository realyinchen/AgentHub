"""Verify controlled research scholar source search.

This check avoids live network calls by monkeypatching the scholarly provider.
It verifies:
- search_research_scholar_sources is gated by Deep Search / Deep Research intent
- provider paper documents become research-scholar-search-v1 plus nested extraction
- scholar search is read-only for app state
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
import app.services.research.source_scholar as source_scholar_service
from app.services.research import (
    ResearchScholarSearchProviderResult,
    ResearchSourceDocument,
)
from app.services.tool_admission import reset_tool_admission_gate
from app.utils.logging import request_id_scope
from app.utils.turn_context import user_message_scope
from scripts.init_database import _init_postgres


VERIFIED_CLAIM = "Scholarly studies describe Example Novel as warm and character-driven."


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
            {"user_id": user_id, "display_name": "Research Scholar Search Verify"},
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
                "title": "Research Scholar Search Verify",
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


async def _search_scholar_sources(**payload: Any) -> dict[str, Any]:
    return json.loads(await research_tools.search_research_scholar_sources.ainvoke(payload))


async def _collect_sources(**payload: Any) -> dict[str, Any]:
    return json.loads(await research_tools.collect_research_sources.ainvoke(payload))


async def _add_evidence(**payload: Any) -> dict[str, Any]:
    return json.loads(await research_tools.add_evidence.ainvoke(payload))


async def _finalize_answer(**payload: Any) -> dict[str, Any]:
    return json.loads(await research_tools.finalize_research_answer.ainvoke(payload))


async def _run_scholar_search_flow() -> None:
    user_id = uuid.uuid4()
    thread_id = uuid.uuid4()
    provider_call_count = 0
    original_provider = source_scholar_service.search_crossref_research_documents

    async def fake_crossref_search(
        *,
        query: str,
        subquestion: str = "",
        limit: int = 5,
        provider_query: str = "",
    ) -> ResearchScholarSearchProviderResult:
        nonlocal provider_call_count
        provider_call_count += 1
        return ResearchScholarSearchProviderResult(
            provider_name="crossref",
            provider_query=provider_query or f"{query} {subquestion}".strip(),
            status="ok",
            documents=[
                ResearchSourceDocument(
                    source_type="paper",
                    source_title="Warmth and Character in Example Novel",
                    source_url="https://doi.org/10.5555/example-novel",
                    content=(
                        f"{VERIFIED_CLAIM} The paper summarizes reader-response "
                        "patterns around warmth, pacing, and character relationships."
                    ),
                    quality="medium",
                    relevance=5,
                    metadata={
                        "provider_source": "crossref",
                        "provider_raw": {"kind": "fake_scholar_result", "rank": 1},
                    },
                ),
                ResearchSourceDocument(
                    source_type="paper",
                    source_title="Unrelated Article",
                    source_url="https://doi.org/10.5555/unrelated",
                    content="This article discusses an unrelated research topic.",
                    quality="medium",
                    relevance=1,
                    metadata={
                        "provider_source": "crossref",
                        "provider_raw": {"kind": "fake_scholar_result", "rank": 2},
                    },
                ),
            ][:limit],
            duration_ms=1,
            metadata={"provider_source": "crossref", "fake": True},
        )

    source_scholar_service.search_crossref_research_documents = fake_crossref_search
    await _insert_temp_user_and_thread(user_id, thread_id)
    try:
        reset_tool_admission_gate()
        with request_id_scope("verify-scholar-search-blocked"):
            with user_message_scope("What is the style of Nonviolent Communication?"):
                blocked = await _search_scholar_sources(
                    query="Example Novel academic study",
                    limit=3,
                )
        _assert(blocked["status"] == "tool_blocked", str(blocked))
        _assert(blocked["result_mode"] == "research_scholar_search", str(blocked))
        _assert(provider_call_count == 0, "blocked tool called provider")

        reset_tool_admission_gate()
        with request_id_scope("verify-scholar-search-flow"):
            with user_message_scope(
                "Please deep research academic evidence about Example Novel warmth."
            ):
                started = await _start_research(
                    user_id=str(user_id),
                    thread_id=str(thread_id),
                    objective="Assess academic evidence that Example Novel is warm.",
                    mode="deep_research",
                    subquestions=["Do scholarly sources describe Example Novel as warm?"],
                    gaps=[],
                    next_actions=["Search scholarly source metadata."],
                    budget={"required_evidence_quality": "medium"},
                    stop_criteria=["One medium-quality paper-backed claim."],
                )
                run_id = started["run"]["id"]
                memory_count_before = await _memory_event_count(user_id)
                step_count_before = await _research_step_count(run_id)
                evidence_count_before = await _evidence_count(run_id)

                scholar_search = await _search_scholar_sources(
                    query="Example Novel warmth character driven academic study",
                    subquestion="Do scholarly sources describe Example Novel as warm?",
                    limit=5,
                )
                _assert(
                    await _research_step_count(run_id) == step_count_before,
                    "scholar search should not write research steps",
                )
                _assert(
                    await _evidence_count(run_id) == evidence_count_before,
                    "scholar search should not write evidence",
                )
                _assert(
                    await _memory_event_count(user_id) == memory_count_before,
                    "scholar search should not write memory",
                )

                records = scholar_search["extraction"]["source_records"]
                collection = await _collect_sources(
                    user_id=str(user_id),
                    run_id=run_id,
                    query=scholar_search["query"],
                    sources=records,
                    subquestion=scholar_search["subquestion"],
                    provider_source="crossref_scholar_search",
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

        _assert(scholar_search["result_mode"] == "research_scholar_search", str(scholar_search))
        _assert(
            scholar_search["contract_version"] == "research-scholar-search-v1",
            str(scholar_search),
        )
        _assert(scholar_search["status"] == "ok", str(scholar_search))
        _assert(scholar_search["provider_name"] == "crossref", str(scholar_search))
        _assert(scholar_search["document_count"] == 2, str(scholar_search))
        _assert(
            scholar_search["source_documents"][0]["source_type"] == "paper",
            str(scholar_search["source_documents"][0]),
        )
        _assert(scholar_search["extracted_count"] >= 1, str(scholar_search))
        _assert(
            scholar_search["metadata"]["external_call"] is True,
            str(scholar_search["metadata"]),
        )
        _assert(
            scholar_search["metadata"]["writes_research_state"] is False,
            str(scholar_search["metadata"]),
        )
        _assert(
            scholar_search["extraction"]["metadata"]["external_call"] is False,
            str(scholar_search["extraction"]["metadata"]),
        )
        _assert(
            collection["metadata"]["writes_research_state"] is True,
            str(collection["metadata"]),
        )
        _assert(final_answer["answer_status"] == "verified", str(final_answer))
        _assert(VERIFIED_CLAIM in final_answer["answer"], final_answer["answer"])
    finally:
        source_scholar_service.search_crossref_research_documents = original_provider
        await _delete_temp_user(user_id)
        reset_tool_admission_gate()


async def _main(skip_migration: bool) -> None:
    load_dotenv()
    if not skip_migration:
        _init_postgres()
    init_embedding_model()
    await init_database()
    try:
        await _run_scholar_search_flow()
    finally:
        await dispose_database()
    print("research scholar search verification passed")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-migration", action="store_true")
    args = parser.parse_args()

    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(_main(skip_migration=args.skip_migration))


if __name__ == "__main__":
    main()
