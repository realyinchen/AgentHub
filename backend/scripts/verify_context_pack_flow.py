"""
Verify Phase M ContextPack / Compression boundaries.

Usage:
    cd backend
    .\\.venv\\Scripts\\python.exe scripts\\verify_context_pack_flow.py

This check avoids LLM and network calls. It verifies:
- ContextPack reads current active memory without writing memory_events
- forgotten memory is redacted from thread summaries
- current active memory outranks summary text in the rendered prompt
- ordinary recommendation ContextPack excludes research state
- Deep Search ContextPack includes only bounded research state and evidence IDs
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import uuid
from pathlib import Path

from dotenv import load_dotenv
from langchain_core.messages import AIMessage, HumanMessage
from sqlalchemy import text

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.infra.database import dispose_database, get_database, init_database
from app.infra.llm.embedding import init_embedding_model
from app.services.book_intent import build_turn_policy
from app.services.context_pack import (
    CompressionSnapshot,
    ContextBuilder,
    render_context_pack_prompt,
)
from app.services.memory import MemoryCandidate, get_memory_orchestrator
from app.services.research import ResearchEvidence, get_research_orchestrator
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
            {"user_id": user_id, "display_name": "Context Pack Verify"},
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
                "title": "Context Pack Verify",
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


async def _run_context_pack_flow() -> None:
    user_id = uuid.uuid4()
    thread_id = uuid.uuid4()
    memory = get_memory_orchestrator()
    research = get_research_orchestrator()
    builder = ContextBuilder()

    await _insert_temp_user_and_thread(user_id, thread_id)
    try:
        active = await memory.remember_candidate(
            MemoryCandidate(
                user_id=user_id,
                thread_id=thread_id,
                type="preference",
                subject="style",
                value="warm character-driven novels",
                polarity="like",
                source_kind="user_message",
                source_text="I like warm character-driven novels.",
            )
        )
        forgotten = await memory.remember_candidate(
            MemoryCandidate(
                user_id=user_id,
                thread_id=thread_id,
                type="preference",
                subject="content",
                value="bloody suspense",
                polarity="avoid",
                source_kind="user_message",
                source_text="I avoid bloody suspense.",
            )
        )
        _assert(active.memory is not None, "active setup memory should write")
        _assert(forgotten.memory is not None, "forgotten setup memory should write")
        await memory.forget_memory(
            user_id=user_id,
            memory_id=forgotten.memory.id,
            thread_id=thread_id,
            reason="phase m summary redaction verification",
        )

        count_before_pack = await _memory_event_count(user_id)
        ordinary_message = "请推荐温暖、人物驱动的小说"
        ordinary_pack = await builder.build(
            user_id=user_id,
            thread_id=thread_id,
            user_message=ordinary_message,
            messages=[
                HumanMessage(content="我不喜欢血腥悬疑"),
                AIMessage(content="已记录。"),
                HumanMessage(content=ordinary_message),
            ],
            turn_policy=build_turn_policy(ordinary_message),
            thread_summary=(
                "Old summary incorrectly says user now likes bloody suspense."
            ),
        )
        rendered = render_context_pack_prompt(ordinary_pack)

        _assert(
            await _memory_event_count(user_id) == count_before_pack,
            "ContextPack build should not write memory_events",
        )
        _assert(
            "warm character-driven novels" in rendered,
            "current active memory should be in rendered ContextPack",
        )
        _assert(
            "bloody suspense" not in ordinary_pack.thread_summary,
            "forgotten memory value should be redacted from summary",
        )
        _assert(
            "[excluded_memory]" in ordinary_pack.thread_summary,
            "redacted summary should keep an exclusion marker",
        )
        _assert(
            forgotten.memory.id in ordinary_pack.denied_memory_ids,
            "forgotten memory id should be denied",
        )
        _assert(
            rendered.index("Current Active Memories")
            < rendered.index("Thread Summary"),
            "current memories should be rendered before summary",
        )
        _assert(
            ordinary_pack.research_state_slice is None,
            "ordinary recommendation context should exclude research state",
        )

        snapshot = CompressionSnapshot(
            thread_id=thread_id,
            summary=ordinary_pack.thread_summary,
            source_message_ids=["m1", "m2"],
            excluded_memory_ids=ordinary_pack.denied_memory_ids,
        )
        _assert(
            snapshot.excluded_memory_ids == ordinary_pack.denied_memory_ids,
            "compression snapshot should preserve excluded memory ids",
        )
        _assert(
            await _memory_event_count(user_id) == count_before_pack,
            "CompressionSnapshot construction should not write memory_events",
        )

        research_state = await research.start_research(
            user_id=user_id,
            thread_id=thread_id,
            objective="Research warm communication books",
            subquestions=["Which communication books are nonviolent and practical?"],
            gaps=["Need source quality checks"],
            next_actions=["Search current sources"],
            budget={"max_steps": 4},
            stop_criteria=["enough verified evidence"],
        )
        run_id = research_state.run.id
        _assert(run_id is not None, "research run should have id")
        with_evidence = await research.add_evidence(
            user_id=user_id,
            run_id=run_id,
            evidence=ResearchEvidence(
                run_id=run_id,
                source_type="web",
                source_title="Example source",
                source_url="https://example.invalid/source",
                claim="Nonviolent Communication emphasizes needs and empathy.",
                excerpt="This excerpt must not be inserted into ContextPack.",
                quality="high",
                relevance=5,
            ),
            known_facts=["NVC emphasizes needs and empathy."],
            gaps=["Need comparison with similar books."],
            next_actions=["Compare adjacent titles."],
        )
        evidence_ids = with_evidence.state.evidence_ids
        _assert(evidence_ids, "research state should expose evidence ids")

        deep_message = "请 deep research 非暴力沟通相关书籍"
        deep_pack = await builder.build(
            user_id=user_id,
            thread_id=thread_id,
            user_message=deep_message,
            messages=[HumanMessage(content=deep_message)],
            turn_policy=build_turn_policy(deep_message),
        )
        deep_rendered = render_context_pack_prompt(deep_pack)
        _assert(
            deep_pack.research_state_slice is not None,
            "deep search context should include research state slice",
        )
        _assert(
            deep_pack.research_state_slice.evidence_ids == evidence_ids,
            "research slice should carry evidence ids",
        )
        _assert(
            "This excerpt must not be inserted" not in deep_rendered,
            "research evidence excerpts should be excluded from ContextPack prompt",
        )
        _assert(
            "evidence_ids:" in deep_rendered,
            "rendered research slice should expose evidence ids",
        )

        print("context pack verification passed")
        print(f"user_id={user_id}")
        print(f"thread_id={thread_id}")
        print(f"run_id={run_id}")
    finally:
        await _delete_temp_user(user_id)


async def _main(skip_migration: bool) -> None:
    load_dotenv()
    if not skip_migration:
        _init_postgres()
    init_embedding_model()
    await init_database()
    try:
        await _run_context_pack_flow()
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
