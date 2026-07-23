r"""Verify generic user-state memory without live LLM calls.

This covers raw-first persistence, open-vocabulary organization, recall,
short-term TTL, timeline conflicts, user confirmation, and fresh web routing.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import uuid
from datetime import timedelta
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import text


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.infra.database import dispose_database, get_database, init_database
from app.infra.llm.embedding import init_embedding_model
from app.models.base import utc_now
from app.schemas.chat import UserInput
from app.services.fast_path import decide_fast_path
from app.services.memory import get_memory_orchestrator
from app.services.memory.user_state import (
    UserStateConfirmation,
    UserStateOrganization,
    apply_user_state_organization,
    confirm_user_state,
    decide_user_state_capture,
    persist_raw_user_state,
)
from app.services.turn_execution import build_turn_execution_plan
from scripts.init_database import _init_postgres


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


async def _seed(user_id: uuid.UUID, thread_ids: list[uuid.UUID]) -> None:
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
            {"user_id": user_id, "display_name": "Generic Memory Verify"},
        )
        for thread_id in thread_ids:
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
                    "title": "Generic Memory Verify",
                },
            )


async def _cleanup(user_id: uuid.UUID) -> None:
    db = get_database()
    async with db.session() as session:
        await session.execute(
            text("DELETE FROM public.users WHERE id = :user_id"),
            {"user_id": user_id},
        )


async def _save(
    *,
    user_id: uuid.UUID,
    thread_id: uuid.UUID,
    text_value: str,
    explicit: bool,
) -> uuid.UUID:
    result = await persist_raw_user_state(
        user_id=user_id,
        thread_id=thread_id,
        raw_text=text_value,
        explicit=explicit,
        schedule_organization=False,
    )
    _assert(result.memory is not None and result.memory.id is not None, str(result))
    _assert(result.memory.state_status == "pending", str(result.memory))
    _assert(result.memory.raw_text == text_value, str(result.memory))
    return result.memory.id


async def _run() -> None:
    user_id = uuid.uuid4()
    first_thread = uuid.uuid4()
    second_thread = uuid.uuid4()
    await _seed(user_id, [first_thread, second_thread])
    try:
        explicit_text = "请记住我有一辆银色电动车，名字叫小银"
        explicit_input = UserInput(
            content=explicit_text,
            user_id=user_id,
            thread_id=first_thread,
            request_id="generic-explicit",
        )
        explicit_gate = decide_fast_path(explicit_input)
        _assert(
            explicit_gate.handled
            and explicit_gate.intent == "memory_write"
            and explicit_gate.metadata.get("generic_user_state") is True,
            str(explicit_gate),
        )

        clothing_text = "我有一件红色冲锋衣，平时下雨徒步时会穿"
        task_text = "我下周三要提交季度复盘"
        _assert(decide_user_state_capture(clothing_text).should_capture, clothing_text)
        _assert(decide_user_state_capture(task_text).should_capture, task_text)
        _assert(
            not decide_user_state_capture("帮我查一下巴黎今天的天气").should_capture,
            "task request was treated as user state",
        )

        clothing_id = await _save(
            user_id=user_id,
            thread_id=first_thread,
            text_value=clothing_text,
            explicit=False,
        )
        await apply_user_state_organization(
            memory_id=clothing_id,
            user_id=user_id,
            proposal=UserStateOrganization(
                category="relation",
                state_key="relation.owns.clothing.red_hiking_jacket",
                summary="用户有一件红色冲锋衣",
                state_value={"item": "冲锋衣", "color": "红色"},
                relation={
                    "subject": "user",
                    "predicate": "owns",
                    "object": "红色冲锋衣",
                    "object_type": "clothing",
                },
                use_when=["用户询问自己的衣服", "下雨徒步装备建议"],
                confidence=0.98,
            ),
        )

        task_id = await _save(
            user_id=user_id,
            thread_id=first_thread,
            text_value=task_text,
            explicit=False,
        )
        task = await apply_user_state_organization(
            memory_id=task_id,
            user_id=user_id,
            proposal=UserStateOrganization(
                category="short_term",
                state_key="short_term.task.quarterly_review",
                summary="用户下周三要提交季度复盘",
                state_value={"task": "提交季度复盘", "deadline": "下周三"},
                use_when=["用户询问近期任务", "安排下周计划"],
                confidence=0.9,
                ttl_hours=24 * 14,
            ),
        )
        _assert(task.valid_until is not None and task.valid_until > utc_now(), str(task))

        recall = await get_memory_orchestrator().search_memory(
            user_id=user_id,
            query="我的衣服",
            limit=10,
        )
        _assert(
            any(item.id == clothing_id for item in recall.relevant_events),
            str(recall.relevant_events),
        )

        lookup = decide_fast_path(
            UserInput(
                content="我的衣服是什么？",
                user_id=user_id,
                thread_id=second_thread,
                request_id="generic-lookup",
            )
        )
        _assert(
            lookup.handled
            and lookup.intent == "memory_lookup"
            and lookup.metadata.get("query") == "衣服",
            str(lookup),
        )

        shanghai_id = await _save(
            user_id=user_id,
            thread_id=first_thread,
            text_value="我现在住在上海",
            explicit=False,
        )
        await apply_user_state_organization(
            memory_id=shanghai_id,
            user_id=user_id,
            proposal=UserStateOrganization(
                category="profile",
                state_key="profile.residence.city",
                summary="用户现在住在上海",
                state_value={"city": "上海"},
                use_when=["本地生活建议", "用户询问居住地"],
                confidence=0.98,
            ),
        )
        beijing_id = await _save(
            user_id=user_id,
            thread_id=second_thread,
            text_value="我现在住在北京",
            explicit=False,
        )
        beijing = await apply_user_state_organization(
            memory_id=beijing_id,
            user_id=user_id,
            proposal=UserStateOrganization(
                category="profile",
                state_key="profile.residence.city",
                summary="用户现在住在北京",
                state_value={"city": "北京"},
                use_when=["本地生活建议", "用户询问居住地"],
                confidence=0.98,
            ),
        )
        _assert(beijing.state_status == "needs_confirmation", str(beijing))
        confirmed = await confirm_user_state(
            user_id=user_id,
            memory_id=beijing_id,
            confirmation=UserStateConfirmation(accept=True),
        )
        _assert(confirmed.state_status == "active", str(confirmed))

        history = await get_memory_orchestrator().list_memory_events(
            user_id=user_id,
            include_superseded=True,
            limit=100,
        )
        old_city = next(item for item in history.events if item.id == shanghai_id)
        _assert(old_city.superseded_by == beijing_id, str(old_city))

        fresh_plan = await build_turn_execution_plan(
            user_message="目前主流AI工具有哪些？",
            user_id=user_id,
            thread_id=second_thread,
        )
        required = {
            item.tool_name
            for item in fresh_plan.required_actions
            if item.decision == "required"
        }
        _assert("web_search" in required, str(fresh_plan))

        print("generic user-state memory verification passed")
        print(f"raw_write_ids={[str(clothing_id), str(task_id)]}")
        print(f"clothing_recall_count={len(recall.relevant_events)}")
        print(f"conflict_status_before_confirm={beijing.state_status}")
        print(f"fresh_required_tools={sorted(required)}")
    finally:
        await _cleanup(user_id)


async def _main(skip_migration: bool) -> None:
    load_dotenv()
    if not skip_migration:
        _init_postgres()
    init_embedding_model()
    await init_database()
    try:
        await _run()
    finally:
        await dispose_database()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-migration", action="store_true")
    args = parser.parse_args()
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(_main(args.skip_migration))


if __name__ == "__main__":
    main()
