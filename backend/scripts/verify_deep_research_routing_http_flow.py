"""Verify the canonical Deep Research chain against a running backend."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import uuid
from pathlib import Path

import httpx
from dotenv import load_dotenv
from sqlalchemy import text


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.infra.database import dispose_database, get_database, init_database
from app.infra.llm.embedding import init_embedding_model
BASE_URL = "http://127.0.0.1:8080/api/v1"


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


async def _seed_user(user_id: uuid.UUID) -> None:
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
            {"user_id": user_id, "display_name": "Deep Routing HTTP Verify"},
        )


async def _cleanup(user_id: uuid.UUID) -> None:
    db = get_database()
    async with db.session() as session:
        await session.execute(
            text("DELETE FROM public.users WHERE id = :user_id"),
            {"user_id": user_id},
        )


async def _run(user_content: str) -> None:
    user_id = uuid.uuid4()
    thread_id = uuid.uuid4()
    request_id = f"deep-routing-{uuid.uuid4()}"
    await _seed_user(user_id)
    try:
        async with httpx.AsyncClient(base_url=BASE_URL, timeout=120) as client:
            response = await client.post(
                "/chat/invoke",
                json={
                    "content": user_content,
                    "user_id": str(user_id),
                    "thread_id": str(thread_id),
                    "request_id": request_id,
                },
            )
            _assert(response.status_code == 200, response.text)
            payload = response.json()
            answer_content = str(payload.get("content") or "")
            custom = payload.get("custom_data") or {}
            plan = custom.get("action_plan") or {}
            tool_info = custom.get("tool_info") or []
            operations = [str(item.get("name") or "") for item in tool_info]
            _assert(plan.get("response_mode") == "receipt", str(plan))
            _assert(
                operations
                == [
                    "start_research",
                    "plan_research_search",
                    "acquire_research_sources",
                    "collect_research_sources",
                    "add_evidence",
                    "evaluate_research_gaps",
                    "plan_research_search",
                    "acquire_research_sources",
                    "collect_research_sources",
                    "add_evidence",
                    "evaluate_research_gaps",
                    "build_research_report",
                    "synthesize_research_answer",
                    "publish_research_answer",
                ],
                str(tool_info),
            )
            _assert("search_research_sources" not in operations, str(operations))
            task_payloads = [
                _tool_output(item)
                for item in tool_info
                if item.get("name") == "plan_research_search"
            ]
            source_payloads = [
                _tool_output(item)
                for item in tool_info
                if item.get("name") == "acquire_research_sources"
            ]
            gap_payloads = [
                _tool_output(item)
                for item in tool_info
                if item.get("name") == "evaluate_research_gaps"
            ]
            _assert(len(task_payloads) == 2, str(task_payloads))
            _assert(len(source_payloads) == 2, str(source_payloads))
            _assert(len(gap_payloads) == 2, str(gap_payloads))
            _assert(task_payloads[0].get("should_search") is True, str(task_payloads))
            expected_time_range = (
                "year"
                if any(
                    marker in user_content
                    for marker in ("最新", "最近", "近期", "今年")
                )
                else None
            )
            _assert(
                task_payloads[0].get("time_range") == expected_time_range,
                str(task_payloads),
            )
            _assert(task_payloads[0].get("detail") == "deep", str(task_payloads))
            if "豆瓣" in user_content:
                _assert(
                    task_payloads[0].get("include_domains")
                    == ["book.douban.com"],
                    str(task_payloads),
                )
                _assert(
                    task_payloads[0].get("include_url_prefixes")
                    == ["https://book.douban.com/subject/"],
                    str(task_payloads),
                )
            _assert(source_payloads[0].get("executed") is True, str(source_payloads))
            _assert(
                source_payloads[1].get("executed")
                == bool(gap_payloads[0].get("should_continue")),
                str({"sources": source_payloads, "gaps": gap_payloads}),
            )
            _assert(
                all(
                    isinstance(description, str)
                    and description
                    and not description.startswith("missing_")
                    for payload in gap_payloads
                    for description in payload.get("gap_descriptions") or []
                ),
                str(gap_payloads),
            )
            _assert(
                gap_payloads[-1].get("stop_reason")
                in {
                    "evidence_satisfied",
                    "search_budget_exhausted",
                    "previous_round_satisfied",
                },
                str(gap_payloads),
            )
            _assert("<tool_call>" not in answer_content, answer_content)
            _assert("<function=" not in answer_content, answer_content)
            _assert(bool(answer_content.strip()), str(payload))
            _assert("## 研究结论" in answer_content, answer_content)
            _assert("Limitations:" not in answer_content, answer_content)
            _assert(
                "CurrentMemory was used" not in answer_content,
                answer_content,
            )
            _assert(
                max((len(line) for line in answer_content.splitlines()), default=0)
                <= 600,
                answer_content,
            )

            statuses = {
                str(item.get("name") or ""): str(item.get("status") or "")
                for item in tool_info
            }
            final_output = next(
                item.get("output")
                for item in tool_info
                if item.get("name") == "publish_research_answer"
            )
            try:
                final_payload = json.loads(str(final_output or "{}"))
            except json.JSONDecodeError:
                final_payload = {}
            _assert(
                final_payload.get("result_mode") == "research_published_answer",
                str(final_payload),
            )
            _assert(final_payload.get("answer") == answer_content, str(final_payload))
            findings = ((final_payload.get("brief") or {}).get("findings") or [])
            _assert(
                all(len(str(item.get("summary") or "")) <= 280 for item in findings),
                str(findings),
            )
            if "给我5本" in user_content:
                _assert(len(findings) == 5, str(findings))
            _assert(
                final_payload.get("research_status") in {"completed", "failed"},
                str(final_payload),
            )
            research_state = final_payload.get("research_state") or {}
            run_status = (
                (research_state.get("run") or {}).get("status")
                or (research_state.get("state") or {}).get("status")
                or research_state.get("status")
            )
            _assert(run_status != "active", str(research_state))

            dag_response = await client.get(
                f"/traces/{thread_id}/dag/{request_id}",
                params={"user_id": str(user_id)},
            )
            _assert(dag_response.status_code == 200, dag_response.text)
            execution_graph = (
                dag_response.json().get("execution_graph") or {}
            )
            _assert(
                execution_graph.get("contract_version") == "execution-graph-v2",
                str(execution_graph),
            )
            graph_nodes = execution_graph.get("nodes") or []
            graph_edges = execution_graph.get("edges") or []
            _assert(len(graph_nodes) == len(operations) + 2, str(execution_graph))
            incoming = {
                str(node.get("node_id") or ""): 0
                for node in graph_nodes
            }
            for edge in graph_edges:
                target = str(edge.get("target_id") or "")
                incoming[target] = incoming.get(target, 0) + 1
            _assert(
                all(
                    count > 0
                    for node_id, count in incoming.items()
                    if node_id != execution_graph.get("entry_node_id")
                ),
                str(execution_graph),
            )
            print("deep research routing HTTP verification passed")
            print(f"operations={operations}")
            print(f"statuses={statuses}")
            print(f"answer_status={final_payload.get('answer_status')}")
            print(
                "research_loop="
                + json.dumps(
                    {
                        "round_1": gap_payloads[0],
                        "round_2": gap_payloads[1],
                    },
                    ensure_ascii=False,
                )
            )
            print(f"answer_preview={answer_content[:500]}")
    finally:
        await _cleanup(user_id)


async def _main(content: str) -> None:
    load_dotenv()
    init_embedding_model()
    await init_database()
    try:
        await _run(content)
    finally:
        await dispose_database()


def _tool_output(item: dict) -> dict:
    value = item.get("output")
    if isinstance(value, dict):
        return value
    try:
        payload = json.loads(str(value or "{}"))
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--content",
        default="深度搜索下最新的好评图书",
        help="Full user input sent to the running backend.",
    )
    args = parser.parse_args()
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(_main(args.content))
