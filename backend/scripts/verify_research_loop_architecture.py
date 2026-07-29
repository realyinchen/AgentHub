from __future__ import annotations

import asyncio
import sys
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.services.agent_runtime.contracts import (
    ActionReceipt,
    PlanReceipt,
)
from app.services.agent_runtime.execution_graph import build_execution_graph
from app.services.planning.compiler import compile_action_plan
from app.services.research.loop import (
    ResearchLoopBudget,
    acquire_research_round,
    evidence_was_admitted,
    evaluate_research_gaps,
    plan_research_search_task,
    project_research_search_output,
)
from app.services.routing.contracts import RoutingQuery
from app.services.routing.funnel import RoutingFunnel


def _old_list_provider_output() -> dict:
    return {
        "status": "ok",
        "provider": "tavily",
        "query": "最新的好评图书",
        "result": {
            "results": [
                {
                    "title": "中华优秀科普图书榜",
                    "url": "https://example.org/old-list",
                    "published_date": "2026-07-20",
                    "content": (
                        "该活动共有200余家出版机构的3000多种图书参与评选，"
                        "最终推荐了近300种优秀科普读物。"
                    ),
                    "score": 0.9,
                }
            ]
        },
    }


def _current_review_provider_output() -> dict:
    return {
        "status": "ok",
        "provider": "tavily",
        "query": "2026 好评图书",
        "result": {
            "results": [
                {
                    "title": "2026年新书评分榜",
                    "url": "https://reviews.example.org/2026/books",
                    "published_date": "2026-07-22",
                    "content": (
                        "《森林里的朋友》于2026年出版，读者书评综合评分为"
                        "4.8分，并进入年度推荐榜单。"
                    ),
                    "score": 0.95,
                }
            ]
        },
    }


async def _run() -> None:
    assert evidence_was_admitted(
        {
            "steps": [
                {
                    "step_type": "add_evidence",
                    "status": "completed",
                    "output": {
                        "evidence_admission": {
                            "allowed": True,
                        }
                    },
                }
            ]
        }
    )
    assert not evidence_was_admitted(
        {
            "steps": [
                {
                    "step_type": "add_evidence",
                    "status": "skipped",
                    "output": {
                        "evidence_admission": {
                            "allowed": False,
                        }
                    },
                }
            ]
        }
    )
    budget = ResearchLoopBudget(
        max_search_rounds=2,
        min_independent_sources=1,
    )
    first_task = plan_research_search_task(
        objective="最新的好评图书",
        round_index=1,
        budget=budget,
        constraints=[
            {"field": "published_at", "operator": "gte", "value": "最新"},
            {"field": "rating", "operator": "gte", "value": "好评"},
        ],
    )
    assert first_task.should_search
    assert first_task.detail == "deep"
    assert first_task.time_range == "year"
    assert "taobao.com" in first_task.exclude_domains

    first_sources = project_research_search_output(
        task=first_task,
        provider_output=_old_list_provider_output(),
    )
    assert not first_sources.source_records
    assert "missing_recency_evidence" in first_sources.rejection_reason_codes

    first_gaps = evaluate_research_gaps(
        round_index=1,
        rounds=[first_sources],
        budget=budget,
    )
    assert first_gaps.should_continue
    assert "missing_recency_evidence" in first_gaps.gaps
    assert first_gaps.gap_descriptions == [
        "未找到带有明确发布日期、可用于判断“最新”的证据。"
    ]
    assert first_gaps.stop_reason == "continue"

    repair_task = plan_research_search_task(
        objective="最新的好评图书",
        round_index=2,
        budget=budget,
        constraints=[
            {"field": "published_at", "operator": "gte", "value": "最新"},
            {"field": "rating", "operator": "gte", "value": "好评"},
        ],
        previous_assessment=first_gaps,
    )
    assert repair_task.should_search
    assert repair_task.purpose == "gap_repair"
    assert repair_task.query != first_task.query
    assert "出版日期" in repair_task.query

    second_sources = project_research_search_output(
        task=repair_task,
        provider_output=_current_review_provider_output(),
    )
    assert len(second_sources.source_records) == 1
    final_gaps = evaluate_research_gaps(
        round_index=2,
        rounds=[first_sources, second_sources],
        budget=budget,
    )
    assert final_gaps.satisfied
    assert not final_gaps.should_continue
    assert final_gaps.stop_reason == "evidence_satisfied"

    no_op_task = plan_research_search_task(
        objective="最新的好评图书",
        round_index=2,
        budget=budget,
        constraints=[
            {"field": "published_at", "operator": "gte", "value": "最新"},
            {"field": "rating", "operator": "gte", "value": "好评"},
        ],
        previous_assessment=final_gaps.model_copy(
            update={"round_index": 1}
        ),
    )
    called = False

    async def forbidden_executor(_arguments: dict) -> dict:
        nonlocal called
        called = True
        raise AssertionError("no-op task performed an external call")

    no_op_sources = await acquire_research_round(
        task=no_op_task,
        executor=forbidden_executor,
    )
    assert not called
    assert not no_op_sources.executed
    assert no_op_sources.metadata["execution_disposition"] == "no_op"

    exhausted = evaluate_research_gaps(
        round_index=1,
        rounds=[first_sources],
        budget=ResearchLoopBudget(max_search_rounds=1),
    )
    assert not exhausted.should_continue
    assert exhausted.stop_reason == "search_budget_exhausted"

    decision = await RoutingFunnel().decide(
        RoutingQuery(text="深度搜索下最新的好评图书")
    )
    plan = compile_action_plan(decision, goal="深度搜索下最新的好评图书")
    operations = [action.operation for action in plan.actions]
    assert len(operations) == 14
    assert operations.count("plan_research_search") == 2
    assert operations.count("acquire_research_sources") == 2
    assert operations.count("evaluate_research_gaps") == 2
    assert "web_search" not in operations
    assert all(
        "user_id" not in action.arguments
        and "thread_id" not in action.arguments
        for action in plan.actions
    )

    receipt = PlanReceipt(
        plan_id=plan.plan_id,
        request_id="request-loop",
        route_type=plan.route_type,
        intent=plan.intent,
        status="completed",
        actions=[
            ActionReceipt(
                action_id=action.action_id,
                capability=action.capability,
                operation=action.operation,
                status="completed",
                admitted=True,
            )
            for action in plan.actions
        ],
    )
    graph = build_execution_graph(plan, receipt)
    incoming = {node.node_id: 0 for node in graph.nodes}
    for edge in graph.edges:
        incoming[edge.target_id] += 1
    assert all(
        count > 0
        for node_id, count in incoming.items()
        if node_id != graph.entry_node_id
    )
    print("verify_research_loop_architecture: ok")


if __name__ == "__main__":
    asyncio.run(_run())
