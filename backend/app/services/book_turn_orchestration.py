from __future__ import annotations

from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.book_intent import TurnPolicy, build_turn_policy
from app.services.recommendation_constraints import (
    PersonalizedRecommendationConstraints,
    build_personalized_recommendation_constraints,
)
from app.services.recommendation_history import normalize_recommendation_history_mode
from app.services.recommendation_research_workflow import (
    RecommendationResearchWorkflowResult,
    plan_recommendation_research_workflow,
)
from app.services.recommendation_signals import normalize_recommendation_text


BOOK_TURN_ORCHESTRATION_CONTRACT_VERSION = "book-turn-orchestration-v1"
BOOK_TURN_ROUTES = frozenset(
    {
        "answer_question",
        "memory_update",
        "memory_management",
        "recommendation_history",
        "ordinary_recommendation",
        "researched_recommendation",
        "deep_research",
        "research_report",
    }
)


class BookTurnOrchestrationStep(BaseModel):
    name: str
    status: str
    reason: str = ""
    required_inputs: list[str] = Field(default_factory=list)


class BookTurnOrchestrationResult(BaseModel):
    """Read-only entry route for book assistant turns."""

    result_mode: str = "book_turn_orchestration"
    contract_version: str = BOOK_TURN_ORCHESTRATION_CONTRACT_VERSION
    route: str
    query: str = ""
    user_message: str = ""
    history_mode: str = ""
    policy: TurnPolicy
    recommended_next_tools: list[str] = Field(default_factory=list)
    denied_tools: list[str] = Field(default_factory=list)
    response_boundary: str = ""
    route_steps: list[BookTurnOrchestrationStep] = Field(default_factory=list)
    personalization_constraints: PersonalizedRecommendationConstraints | None = None
    recommendation_research_workflow: RecommendationResearchWorkflowResult | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


async def plan_book_assistant_turn(
    session: AsyncSession | None,
    *,
    user_message: str,
    query: str = "",
    user_id: UUID | None = None,
    candidates: list[dict[str, Any]] | None = None,
    research_report: dict[str, Any] | None = None,
    research_state: dict[str, Any] | None = None,
    book_title: str = "",
    metadata: dict[str, Any] | None = None,
) -> BookTurnOrchestrationResult:
    """Plan the app-owned route for one user dialogue turn.

    This is the explicit entrance contract for the flowchart. It routes the
    current dialogue into ordinary recommendation, recommendation history,
    Deep Research, researched recommendation, memory handling, or direct
    answer mode. It is read-only and does not execute the planned tools.
    """

    message = normalize_recommendation_text(user_message)
    normalized_query = normalize_recommendation_text(query) or message
    policy = build_turn_policy(message)
    route = _route_from_policy(policy)
    history_mode = _history_mode_for_route(route, message, book_title)
    constraints: PersonalizedRecommendationConstraints | None = None
    workflow: RecommendationResearchWorkflowResult | None = None
    route_metadata = dict(metadata or {})

    if session is not None and user_id is not None and route in {
        "ordinary_recommendation",
        "researched_recommendation",
    }:
        try:
            constraints = await build_personalized_recommendation_constraints(
                session,
                user_id=user_id,
                query=normalized_query,
            )
        except Exception as exc:
            route_metadata["personalization_constraints_error"] = (
                str(exc) or exc.__class__.__name__
            )

    if user_id is not None and route == "researched_recommendation":
        workflow = plan_recommendation_research_workflow(
            user_id=user_id,
            query=normalized_query,
            candidates=candidates or [],
            research_report=research_report or {},
            research_state=research_state or {},
            personalization_constraints=constraints,
            metadata={"orchestration_phase": "book_turn"},
        )

    next_tools = _next_tools_for_route(
        route=route,
        policy=policy,
        workflow=workflow,
        has_candidates=bool(candidates),
        has_research_report=bool(research_report),
    )
    return BookTurnOrchestrationResult(
        route=route,
        query=normalized_query,
        user_message=message,
        history_mode=history_mode,
        policy=policy,
        recommended_next_tools=next_tools,
        denied_tools=policy.denied_tools,
        response_boundary=policy.response_boundary,
        route_steps=_steps_for_route(
            route=route,
            policy=policy,
            history_mode=history_mode,
            workflow=workflow,
            has_candidates=bool(candidates),
            has_research_report=bool(research_report),
        ),
        personalization_constraints=constraints,
        recommendation_research_workflow=workflow,
        metadata={
            **route_metadata,
            "available_routes": sorted(BOOK_TURN_ROUTES),
            "writes_long_term_memory": False,
            "writes_recommendation_events": False,
            "writes_research_state": False,
            "writes_evidence": False,
            "external_call": False,
            "executes_planned_tools": False,
            "uses_app_owned_contracts": True,
        },
    )


def _route_from_policy(policy: TurnPolicy) -> str:
    intents = set(policy.intent.intents)
    if policy.can_view_recommendation_history:
        return "recommendation_history"
    if policy.can_start_research and policy.can_recommend_books:
        return "researched_recommendation"
    if policy.can_start_research and "research_report" in intents:
        return "research_report"
    if policy.can_start_research:
        return "deep_research"
    if policy.can_recommend_books:
        return "ordinary_recommendation"
    if policy.can_manage_memory:
        return "memory_management"
    if policy.can_write_memory:
        return "memory_update"
    return "answer_question"


def _history_mode_for_route(route: str, user_message: str, book_title: str) -> str:
    if route != "recommendation_history":
        return ""
    lowered = user_message.lower()
    if book_title or "why" in lowered or "为什么" in user_message or "为啥" in user_message:
        return normalize_recommendation_history_mode("suppression_explanation")
    if "拒绝" in user_message or "not interested" in lowered or "rejected" in lowered:
        return normalize_recommendation_history_mode("rejection_history")
    if "已读" in user_message or "读过" in user_message or "reading history" in lowered:
        return normalize_recommendation_history_mode("reading_history")
    return normalize_recommendation_history_mode("all")


def _next_tools_for_route(
    *,
    route: str,
    policy: TurnPolicy,
    workflow: RecommendationResearchWorkflowResult | None,
    has_candidates: bool,
    has_research_report: bool,
) -> list[str]:
    if route == "recommendation_history":
        return ["get_recommendation_history"]
    if route == "ordinary_recommendation":
        tools = ["search_memory"] if policy.can_search_memory else []
        tools.append("search_books")
        return _dedupe(tools)
    if route == "researched_recommendation":
        if workflow is not None and workflow.recommended_next_tools:
            if workflow.status == "needs_candidates":
                return ["search_books", "plan_recommendation_research_workflow"]
            return workflow.recommended_next_tools
        if not has_candidates:
            return ["search_books", "plan_recommendation_research_workflow"]
        if not has_research_report:
            return [
                "search_research_sources",
                "build_research_observations",
                "run_recommendation_research_workflow",
            ]
        return ["plan_recommendation_research_workflow"]
    if route == "deep_research":
        return ["start_research", "search_research_sources", "build_research_report"]
    if route == "research_report":
        return ["inspect_research_state", "build_research_report"]
    if route == "memory_management":
        return ["search_memory", "forget_memory"]
    if route == "memory_update":
        return ["remember_memory", "search_memory"]
    if _policy_recommends_memory_lookup(policy):
        return ["search_memory"]
    if _policy_recommends_web_search(policy):
        return ["web_search"]
    return []


def _steps_for_route(
    *,
    route: str,
    policy: TurnPolicy,
    history_mode: str,
    workflow: RecommendationResearchWorkflowResult | None,
    has_candidates: bool,
    has_research_report: bool,
) -> list[BookTurnOrchestrationStep]:
    if route == "recommendation_history":
        return [
            BookTurnOrchestrationStep(
                name="get_recommendation_history",
                status="ready",
                reason="The user asked for history or suppression explanation.",
                required_inputs=["user_id", "history_mode"],
            ),
            BookTurnOrchestrationStep(
                name="search_books",
                status="blocked_by_route",
                reason="History/explanation mode must not create fresh recommendations.",
            ),
        ]
    if route == "ordinary_recommendation":
        return [
            BookTurnOrchestrationStep(
                name="search_memory",
                status="ready",
                reason="CurrentMemory should inform ordinary recommendations.",
                required_inputs=["user_id"],
            ),
            BookTurnOrchestrationStep(
                name="search_books",
                status="ready",
                reason="The user explicitly asked for book recommendations.",
                required_inputs=["query", "user_id"],
            ),
        ]
    if route == "researched_recommendation":
        steps = [
            BookTurnOrchestrationStep(
                name="search_books",
                status="complete" if has_candidates else "needed",
                reason="Researched recommendations need fresh unsuppressed candidates.",
                required_inputs=[] if has_candidates else ["query", "user_id"],
            )
        ]
        if workflow is not None:
            steps.extend(
                BookTurnOrchestrationStep(
                    name=step.name,
                    status=step.status,
                    reason=step.reason,
                    required_inputs=step.required_inputs,
                )
                for step in workflow.workflow_steps
            )
        else:
            steps.append(
                BookTurnOrchestrationStep(
                    name="plan_recommendation_research_workflow",
                    status="needed",
                    reason="Plan the research/fusion path after candidates or report are available.",
                    required_inputs=["user_id", "query"],
                )
            )
        return steps
    if route == "deep_research":
        return [
            BookTurnOrchestrationStep(
                name="start_research",
                status="needed",
                reason="Deep Research requires structured research state.",
                required_inputs=["user_id", "objective"],
            ),
            BookTurnOrchestrationStep(
                name="build_research_report",
                status="blocked_by_missing_input",
                reason="A report requires a research run with admitted evidence or gaps.",
                required_inputs=["run_id"],
            ),
        ]
    if route == "research_report":
        return [
            BookTurnOrchestrationStep(
                name="build_research_report",
                status="needed",
                reason="The user asked for a research report.",
                required_inputs=["user_id", "run_id"],
            )
        ]
    if route in {"memory_update", "memory_management"}:
        tool = "forget_memory" if route == "memory_management" else "remember_memory"
        return [
            BookTurnOrchestrationStep(
                name=tool,
                status="ready",
                reason="The user turn is about memory state.",
                required_inputs=["user_id"],
            )
        ]
    if _policy_recommends_memory_lookup(policy):
        return [
            BookTurnOrchestrationStep(
                name="search_memory",
                status="ready",
                reason="The user asked about stored profile or memory state.",
                required_inputs=["user_id", "query"],
            )
        ]
    if _policy_recommends_web_search(policy):
        return [
            BookTurnOrchestrationStep(
                name="web_search",
                status="ready",
                reason="The user asked for a time-sensitive or current web fact.",
                required_inputs=["query"],
            )
        ]
    return [
        BookTurnOrchestrationStep(
            name="answer_question",
            status="ready",
            reason="No book recommendation, history, memory, or research action is required.",
        )
    ]


def _policy_recommends_web_search(policy: TurnPolicy) -> bool:
    return bool(policy.intent.metadata.get("web_search_recommended"))


def _policy_recommends_memory_lookup(policy: TurnPolicy) -> bool:
    return bool(policy.intent.metadata.get("memory_lookup"))


def _dedupe(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        key = value.strip().lower()
        if key and key not in seen:
            seen.add(key)
            result.append(value)
    return result
