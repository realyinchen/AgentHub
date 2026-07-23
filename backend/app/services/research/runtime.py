from __future__ import annotations

from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field

from app.services.research.harness import (
    ResearchHarnessInput,
    ResearchHarnessResult,
    ResearchHarnessRuntime,
)
from app.services.research.observation_providers import (
    ResearchObservation,
    SourceObservationProvider,
)
from app.services.research.report import ResearchReport, build_research_report


RESEARCH_RUNTIME_CONTRACT_VERSION = "research-runtime-v1"


class ResearchRuntimeReportResult(BaseModel):
    result_mode: str = "research_runtime"
    contract_version: str = RESEARCH_RUNTIME_CONTRACT_VERSION
    user_id: UUID
    run_id: UUID
    status: str
    harness: ResearchHarnessResult
    report: ResearchReport
    metadata: dict[str, Any] = Field(default_factory=dict)


async def run_research_runtime(
    *,
    user_id: UUID,
    objective: str,
    thread_id: UUID | None = None,
    mode: str = "deep_research",
    subquestions: list[str] | None = None,
    gaps: list[str] | None = None,
    next_actions: list[str] | None = None,
    budget: dict[str, Any] | None = None,
    stop_criteria: list[str] | None = None,
    observations: list[ResearchObservation] | None = None,
    metadata: dict[str, Any] | None = None,
    limit_steps: int = 100,
    limit_evidence: int = 100,
) -> ResearchRuntimeReportResult:
    """Run one local Deep Research harness cycle and project a report.

    This local runtime intentionally uses SourceObservationProvider so the
    cycle operates on app-owned normalized observations supplied by the caller.
    It does not call mem0, gbrain, or any live external transport.
    """

    normalized_observations = [
        ResearchObservation.model_validate(observation)
        for observation in observations or []
    ]
    if not normalized_observations:
        raise ValueError("at least one research observation is required")

    harness = ResearchHarnessRuntime(
        observation_provider=SourceObservationProvider("source")
    )
    harness_result = await harness.run(
        ResearchHarnessInput(
            user_id=user_id,
            thread_id=thread_id,
            objective=objective,
            mode=mode,
            subquestions=subquestions or [],
            gaps=gaps or [],
            next_actions=next_actions or [],
            budget=budget or {},
            stop_criteria=stop_criteria or [],
            observations=normalized_observations,
            metadata={
                **(metadata or {}),
                "runtime": {
                    **((metadata or {}).get("runtime") or {}),
                    "contract_version": RESEARCH_RUNTIME_CONTRACT_VERSION,
                    "provider_mode": "source_observations",
                },
            },
        )
    )
    report = await build_research_report(
        user_id=user_id,
        run_id=harness_result.run_id,
        limit_steps=limit_steps,
        limit_evidence=limit_evidence,
    )
    return ResearchRuntimeReportResult(
        user_id=user_id,
        run_id=harness_result.run_id,
        status=harness_result.status,
        harness=harness_result,
        report=report,
        metadata={
            "writes_research_state": True,
            "writes_long_term_memory": False,
            "writes_recommendation_events": False,
            "external_call": False,
            "provider_mode": "source_observations",
            "observation_count": len(normalized_observations),
            "report_contract_version": report.contract_version,
        },
    )
