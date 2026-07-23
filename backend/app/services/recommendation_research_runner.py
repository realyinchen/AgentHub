from __future__ import annotations

from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field

from app.services.recommendation_constraints import (
    PersonalizedRecommendationConstraints,
)
from app.services.recommendation_research_report import (
    RecommendationResearchReport,
    build_recommendation_research_report,
)
from app.services.recommendation_research_workflow import (
    RecommendationResearchWorkflowResult,
    plan_recommendation_research_workflow,
)
from app.services.research.observation_providers import ResearchObservation
from app.services.research.report import RESEARCH_REPORT_CONTRACT_VERSION, ResearchReport
from app.services.research.runtime import (
    ResearchRuntimeReportResult,
    run_research_runtime,
)


RECOMMENDATION_RESEARCH_RUNNER_CONTRACT_VERSION = (
    "recommendation-research-runner-v1"
)


class RecommendationResearchRunnerResult(BaseModel):
    """Bounded local runner for researched recommendation fusion."""

    result_mode: str = "recommendation_research_runner"
    contract_version: str = RECOMMENDATION_RESEARCH_RUNNER_CONTRACT_VERSION
    status: str
    query: str = ""
    workflow_before: RecommendationResearchWorkflowResult
    workflow_after: RecommendationResearchWorkflowResult
    runtime: ResearchRuntimeReportResult | None = None
    research_report: ResearchReport | None = None
    recommendation_report: RecommendationResearchReport | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


async def run_recommendation_research_workflow(
    *,
    user_id: UUID,
    query: str = "",
    candidates: list[dict[str, Any]] | None = None,
    research_report: dict[str, Any] | None = None,
    observations: list[ResearchObservation] | None = None,
    thread_id: UUID | None = None,
    mode: str = "deep_research",
    subquestions: list[str] | None = None,
    gaps: list[str] | None = None,
    next_actions: list[str] | None = None,
    budget: dict[str, Any] | None = None,
    stop_criteria: list[str] | None = None,
    personalization_constraints: PersonalizedRecommendationConstraints | None = None,
    allow_runtime: bool = True,
    metadata: dict[str, Any] | None = None,
    limit_steps: int = 100,
    limit_evidence: int = 100,
) -> RecommendationResearchRunnerResult:
    """Run the local researched recommendation path when inputs are ready.

    This runner never searches for books, fetches sources, or calls live
    provider transports. It can run the local research harness only over
    caller-supplied app-owned observations, then fuses existing candidates with
    the resulting verified report.
    """

    candidate_items = [
        dict(candidate) for candidate in candidates or [] if isinstance(candidate, dict)
    ]
    normalized_observations = [
        ResearchObservation.model_validate(observation)
        for observation in observations or []
    ]
    initial_report_payload = dict(research_report or {})
    workflow_before = plan_recommendation_research_workflow(
        user_id=user_id,
        query=query,
        candidates=candidate_items,
        research_report=initial_report_payload,
        personalization_constraints=personalization_constraints,
        metadata={"runner_phase": "before"},
    )

    runtime_result: ResearchRuntimeReportResult | None = None
    report_model: ResearchReport | None = None
    report_payload = initial_report_payload
    if _valid_report_payload(report_payload):
        report_model = ResearchReport.model_validate(report_payload)

    should_run_runtime = (
        allow_runtime
        and bool(candidate_items)
        and bool(normalized_observations)
        and not workflow_before.ready_to_fuse
    )
    if should_run_runtime:
        runtime_result = await run_research_runtime(
            user_id=user_id,
            objective=query or "Research recommendation candidates.",
            thread_id=thread_id,
            mode=mode,
            subquestions=subquestions or [],
            gaps=gaps or [],
            next_actions=next_actions or [],
            budget=budget or {},
            stop_criteria=stop_criteria or [],
            observations=normalized_observations,
            metadata={
                **(metadata or {}),
                "recommendation_research_runner": {
                    "contract_version": RECOMMENDATION_RESEARCH_RUNNER_CONTRACT_VERSION,
                },
            },
            limit_steps=limit_steps,
            limit_evidence=limit_evidence,
        )
        report_model = runtime_result.report
        report_payload = report_model.model_dump(mode="json")

    workflow_after = plan_recommendation_research_workflow(
        user_id=user_id,
        query=query,
        candidates=candidate_items,
        research_report=report_payload,
        personalization_constraints=personalization_constraints,
        metadata={"runner_phase": "after"},
    )

    recommendation_report: RecommendationResearchReport | None = None
    if workflow_after.ready_to_fuse:
        recommendation_report = build_recommendation_research_report(
            query=query,
            candidates=candidate_items,
            research_report=report_payload,
            metadata={
                "runner_contract_version": RECOMMENDATION_RESEARCH_RUNNER_CONTRACT_VERSION,
                "runner_runtime_executed": runtime_result is not None,
            },
        )

    return RecommendationResearchRunnerResult(
        status=_runner_status(
            workflow_after=workflow_after,
            recommendation_report=recommendation_report,
            runtime_executed=runtime_result is not None,
            observations=normalized_observations,
            candidates=candidate_items,
            allow_runtime=allow_runtime,
        ),
        query=query,
        workflow_before=workflow_before,
        workflow_after=workflow_after,
        runtime=runtime_result,
        research_report=report_model,
        recommendation_report=recommendation_report,
        metadata={
            **(metadata or {}),
            "writes_research_state": runtime_result is not None,
            "writes_evidence": runtime_result is not None,
            "writes_long_term_memory": False,
            "writes_recommendation_events": False,
            "external_call": False,
            "provider_mode": "source_observations",
            "candidate_count": len(candidate_items),
            "observation_count": len(normalized_observations),
            "runtime_executed": runtime_result is not None,
            "allow_runtime": allow_runtime,
            "fusion_executed": recommendation_report is not None,
        },
    )


def _valid_report_payload(payload: dict[str, Any]) -> bool:
    return payload.get("contract_version") == RESEARCH_REPORT_CONTRACT_VERSION


def _runner_status(
    *,
    workflow_after: RecommendationResearchWorkflowResult,
    recommendation_report: RecommendationResearchReport | None,
    runtime_executed: bool,
    observations: list[ResearchObservation],
    candidates: list[dict[str, Any]],
    allow_runtime: bool,
) -> str:
    if recommendation_report is not None:
        return "fused"
    if not candidates:
        return "needs_candidates"
    if workflow_after.status == "needs_verified_research" and not observations:
        return "needs_observations"
    if not allow_runtime and workflow_after.status != "ready_to_fuse":
        return "runtime_disabled"
    if runtime_executed:
        return workflow_after.status
    return workflow_after.status
