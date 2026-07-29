"""Verify the three-stage RoutingDecision contract without live providers."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from pydantic import ValidationError


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.services.planning.compiler import compile_action_plan
from app.services.routing.contracts import (
    IntentCandidate,
    ProposedAction,
    RoutingQuery,
)
from app.services.routing.funnel import RoutingFunnel
from app.services.routing.semantic import InMemorySemanticRecall


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


class _NoLiveVectorSemantic(InMemorySemanticRecall):
    async def _vector_candidates(self, text: str):
        del text
        return []


class _FutureMemoryRouter:
    async def classify(self, query: RoutingQuery) -> list[IntentCandidate]:
        return [
            IntentCandidate(
                intent="memory_update",
                confidence=0.90,
                source="router_model",
                evidence=[f"future_model:{query.text}"],
                domain="memory",
            )
        ]


async def _run() -> None:
    funnel = RoutingFunnel(semantic_provider=_NoLiveVectorSemantic())
    cases = [
        ("我是谁？", "memory_lookup", ["search_memory"], "fast_path"),
        (
            "我现在不叫冰露，我现在叫鲁班",
            "memory_update",
            ["process_memory_write_request"],
            "fast_path",
        ),
        ("今天天气怎么样？", "weather_lookup", ["web_search"], "slow_path"),
        ("什么是递归？", "answer_question", [], "fast_path"),
        ("法国总统是谁？", "external_lookup", ["web_search"], "slow_path"),
        (
            "深度搜索下最新的好评图书",
            "deep_research",
            [
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
            "slow_path",
        ),
    ]
    for text, intent, operations, route_type in cases:
        decision = await funnel.decide(RoutingQuery(text=text))
        _assert(decision.primary_intent == intent, str(decision))
        _assert(
            [item.operation for item in decision.proposed_actions] == operations,
            str(decision),
        )
        _assert(decision.route_type == route_type, str(decision))
        plan = compile_action_plan(decision, goal=text)
        _assert(
            [item.operation for item in plan.actions] == operations,
            str(plan),
        )
        for action in plan.actions:
            _assert("user_id" not in action.arguments, str(action))
            _assert("thread_id" not in action.arguments, str(action))

    identity = await funnel.decide(RoutingQuery(text="我是谁？"))
    _assert(identity.metadata.get("layers_used") == ["layer0_rule"], str(identity))

    deep = await funnel.decide(RoutingQuery(text="深度搜索下最新的好评图书"))
    first_plan = deep.proposed_actions[1]
    second_plan = deep.proposed_actions[6]
    _assert(first_plan.operation == "plan_research_search", str(deep))
    _assert(first_plan.arguments["objective"] == "最新的好评图书", str(deep))
    _assert(first_plan.arguments["round_index"] == 1, str(deep))
    _assert(second_plan.arguments["round_index"] == 2, str(deep))
    _assert(
        first_plan.arguments["budget"]["max_search_rounds"] == 2,
        str(deep),
    )
    _assert(
        first_plan.arguments["budget"]["min_independent_sources"] == 2,
        str(deep),
    )
    _assert(deep.policy["can_use_web_search"] is True, str(deep))
    _assert(deep.requirements.decomposition_required, str(deep))
    _assert(deep.requirements.external_search_required, str(deep))

    douban = await funnel.decide(
        RoutingQuery(text="深度搜索下豆瓣好评图书，给我5本好书推荐。")
    )
    constraint_fields = {item.field for item in douban.constraints}
    _assert(
        {"source_domain", "rating", "result_limit"}.issubset(
            constraint_fields
        ),
        str(douban.constraints),
    )
    douban_plan_action = next(
        item
        for item in douban.proposed_actions
        if item.operation == "plan_research_search"
    )
    plan_constraint_fields = {
        item["field"]
        for item in douban_plan_action.arguments["constraints"]
    }
    _assert(
        {"source_domain", "rating", "result_limit"}.issubset(
            plan_constraint_fields
        ),
        str(douban_plan_action.arguments),
    )
    _assert(
        douban_plan_action.arguments["budget"]["min_independent_sources"] == 1,
        str(douban_plan_action.arguments),
    )
    _assert(
        douban_plan_action.arguments["budget"]["max_records_per_round"] == 5,
        str(douban_plan_action.arguments),
    )

    future_funnel = RoutingFunnel(
        semantic_provider=_NoLiveVectorSemantic(),
        router_model_provider=_FutureMemoryRouter(),
    )
    future = await future_funnel.decide(RoutingQuery(text="鲁班乃吾名"))
    _assert(future.primary_intent == "memory_update", str(future))
    _assert(
        [item.operation for item in future.proposed_actions]
        == ["process_memory_write_request"],
        str(future),
    )
    _assert(future.policy["can_write_memory"] is True, str(future))
    _assert(
        future.policy["metadata"]["derived_from_routing_decision"] is True,
        str(future),
    )
    _assert(
        future.metadata["layers_used"][-1] == "layer2_router_model",
        str(future),
    )

    try:
        ProposedAction(
            action_key="invalid",
            capability="memory",
            operation="search_memory",
            arguments={"user_id": "forbidden"},
        )
    except ValidationError:
        pass
    else:
        raise AssertionError("RoutingDecision accepted a system-owned field")

    try:
        ProposedAction(
            action_key="invalid_nested",
            capability="research",
            operation="start_research",
            arguments={"metadata": {"thread_id": "forbidden"}},
        )
    except ValidationError:
        pass
    else:
        raise AssertionError(
            "RoutingDecision accepted a nested system-owned field"
        )

    try:
        RoutingQuery(text="hello", user_id="forbidden")  # type: ignore[call-arg]
    except ValidationError:
        pass
    else:
        raise AssertionError("RoutingQuery accepted a system-owned field")

    try:
        IntentCandidate(
            intent="memory_update",
            confidence=0.9,
            source="rule",
            operations=["process_memory_write_request"],  # type: ignore[call-arg]
        )
    except ValidationError:
        pass
    else:
        raise AssertionError("IntentCandidate accepted executable operations")

    print("routing-decision verification passed")


if __name__ == "__main__":
    asyncio.run(_run())
