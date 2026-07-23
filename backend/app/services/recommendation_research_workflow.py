from __future__ import annotations

from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field

from app.services.recommendation_constraints import (
    PersonalizedRecommendationConstraints,
)
from app.services.recommendation_research_report import (
    RECOMMENDATION_RESEARCH_REPORT_CONTRACT_VERSION,
)
from app.services.recommendation_signals import normalize_recommendation_text
from app.services.research.report import RESEARCH_REPORT_CONTRACT_VERSION


RECOMMENDATION_RESEARCH_WORKFLOW_CONTRACT_VERSION = (
    "recommendation-research-workflow-v1"
)


class RecommendationResearchWorkflowStep(BaseModel):
    name: str
    status: str
    reason: str = ""
    required_inputs: list[str] = Field(default_factory=list)


class RecommendationResearchWorkflowResult(BaseModel):
    """Read-only workflow readiness contract for researched recommendations."""

    result_mode: str = "recommendation_research_workflow"
    contract_version: str = RECOMMENDATION_RESEARCH_WORKFLOW_CONTRACT_VERSION
    status: str
    query: str = ""
    ready_to_fuse: bool = False
    candidate_count: int = 0
    fresh_candidate_count: int = 0
    suppressed_candidate_count: int = 0
    research_run_id: str = ""
    research_report_status: str = ""
    research_report_contract_version: str = ""
    verified_claim_count: int = 0
    missing_inputs: list[str] = Field(default_factory=list)
    recommended_next_tools: list[str] = Field(default_factory=list)
    next_action_hint: str = ""
    workflow_steps: list[RecommendationResearchWorkflowStep] = Field(
        default_factory=list
    )
    personalization_constraints: PersonalizedRecommendationConstraints | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


def plan_recommendation_research_workflow(
    *,
    user_id: UUID,
    query: str = "",
    candidates: list[dict[str, Any]] | None = None,
    research_report: dict[str, Any] | None = None,
    research_state: dict[str, Any] | None = None,
    personalization_constraints: PersonalizedRecommendationConstraints | None = None,
    metadata: dict[str, Any] | None = None,
) -> RecommendationResearchWorkflowResult:
    """Plan the next read-only step for a researched recommendation turn.

    The planner does not search books, run research, admit evidence, build
    reports, write memory, write recommendation events, or call provider
    transports. It only makes the current workflow readiness explicit so the
    agent can call the right existing app-owned tool next.
    """

    normalized_query = normalize_recommendation_text(query)
    candidate_items = [dict(item) for item in candidates or [] if isinstance(item, dict)]
    suppressed_count = sum(1 for item in candidate_items if _candidate_suppressed(item))
    candidate_count = len(candidate_items)
    fresh_candidate_count = max(0, candidate_count - suppressed_count)

    report_payload = dict(research_report or {})
    state_payload = dict(research_state or {})
    report_contract = normalize_recommendation_text(
        report_payload.get("contract_version")
    )
    report_status = normalize_recommendation_text(report_payload.get("report_status"))
    verified_claim_count = len(_claim_dicts(report_payload.get("verified_claims")))
    research_run_id = _research_run_id(report_payload=report_payload, state=state_payload)

    missing_inputs: list[str] = []
    next_tools: list[str] = []
    steps: list[RecommendationResearchWorkflowStep] = []

    if fresh_candidate_count == 0:
        missing_inputs.append("fresh_book_candidates")
        next_tools.append("search_books")
        steps.append(
            RecommendationResearchWorkflowStep(
                name="search_books",
                status="needed",
                reason="No fresh unsuppressed recommendation candidates are available.",
                required_inputs=["query", "user_id"],
            )
        )
    else:
        steps.append(
            RecommendationResearchWorkflowStep(
                name="search_books",
                status="complete",
                reason="Fresh unsuppressed book candidates are available.",
            )
        )

    report_valid = report_contract == RESEARCH_REPORT_CONTRACT_VERSION
    if not report_valid:
        if research_run_id:
            missing_inputs.append("research_report")
            next_tools.append("build_research_report")
            steps.append(
                RecommendationResearchWorkflowStep(
                    name="build_research_report",
                    status="needed",
                    reason="A research run exists but no valid research-report-v1 was provided.",
                    required_inputs=["user_id", "run_id"],
                )
            )
        else:
            missing_inputs.append("research_run")
            next_tools.extend(
                [
                    "start_research",
                    "search_research_sources",
                    "collect_research_sources",
                    "add_evidence",
                    "build_research_report",
                ]
            )
            steps.extend(
                [
                    RecommendationResearchWorkflowStep(
                        name="start_research",
                        status="needed",
                        reason="No research run is available for this recommendation.",
                        required_inputs=["user_id", "query"],
                    ),
                    RecommendationResearchWorkflowStep(
                        name="search_research_sources",
                        status="needed",
                        reason="Source-backed evidence is needed before recommendation support can be verified.",
                        required_inputs=["query"],
                    ),
                    RecommendationResearchWorkflowStep(
                        name="collect_research_sources",
                        status="blocked_by_missing_input",
                        reason="Requires an existing research run and approved source records.",
                        required_inputs=["run_id", "sources"],
                    ),
                    RecommendationResearchWorkflowStep(
                        name="add_evidence",
                        status="blocked_by_missing_input",
                        reason="Requires source-backed claim, excerpt, and source metadata.",
                        required_inputs=["run_id", "claim", "excerpt", "source"],
                    ),
                    RecommendationResearchWorkflowStep(
                        name="build_research_report",
                        status="blocked_by_missing_input",
                        reason="Requires a research run with admitted evidence or explicit gaps.",
                        required_inputs=["user_id", "run_id"],
                    ),
                ]
            )
    elif verified_claim_count == 0:
        missing_inputs.append("verified_research_claims")
        next_tools.extend(["search_research_sources", "add_evidence", "build_research_report"])
        steps.append(
            RecommendationResearchWorkflowStep(
                name="build_research_report",
                status="needs_stronger_evidence",
                reason="A research report exists, but it has no verified claims to support candidates.",
                required_inputs=["admitted_evidence"],
            )
        )
    else:
        steps.append(
            RecommendationResearchWorkflowStep(
                name="build_research_report",
                status="complete",
                reason="A valid research-report-v1 with verified claims is available.",
            )
        )

    ready_to_fuse = fresh_candidate_count > 0 and report_valid and verified_claim_count > 0
    if ready_to_fuse:
        next_tools = ["build_recommendation_research_report"]
        steps.append(
            RecommendationResearchWorkflowStep(
                name="build_recommendation_research_report",
                status="ready",
                reason="Fresh candidates and verified research claims are available.",
                required_inputs=["candidates", "research_report"],
            )
        )
    else:
        steps.append(
            RecommendationResearchWorkflowStep(
                name="build_recommendation_research_report",
                status="blocked_by_missing_input",
                reason="Fusion requires fresh candidates and a valid research-report-v1 with verified claims.",
                required_inputs=_dedupe(missing_inputs),
            )
        )

    status = _workflow_status(
        fresh_candidate_count=fresh_candidate_count,
        report_valid=report_valid,
        research_run_id=research_run_id,
        verified_claim_count=verified_claim_count,
        ready_to_fuse=ready_to_fuse,
    )
    unique_next_tools = _dedupe(next_tools)
    return RecommendationResearchWorkflowResult(
        status=status,
        query=normalized_query,
        ready_to_fuse=ready_to_fuse,
        candidate_count=candidate_count,
        fresh_candidate_count=fresh_candidate_count,
        suppressed_candidate_count=suppressed_count,
        research_run_id=research_run_id,
        research_report_status=report_status,
        research_report_contract_version=report_contract,
        verified_claim_count=verified_claim_count,
        missing_inputs=_dedupe(missing_inputs),
        recommended_next_tools=unique_next_tools,
        next_action_hint=_next_action_hint(status, unique_next_tools),
        workflow_steps=steps,
        personalization_constraints=personalization_constraints,
        metadata={
            **(metadata or {}),
            "user_id": str(user_id),
            "writes_research_state": False,
            "writes_evidence": False,
            "writes_long_term_memory": False,
            "writes_recommendation_events": False,
            "external_call": False,
            "uses_app_owned_contracts": True,
            "requires_research_report_contract": RESEARCH_REPORT_CONTRACT_VERSION,
            "produces_fusion_contract": RECOMMENDATION_RESEARCH_REPORT_CONTRACT_VERSION,
        },
    )


def _workflow_status(
    *,
    fresh_candidate_count: int,
    report_valid: bool,
    research_run_id: str,
    verified_claim_count: int,
    ready_to_fuse: bool,
) -> str:
    if ready_to_fuse:
        return "ready_to_fuse"
    if fresh_candidate_count == 0:
        return "needs_candidates"
    if not report_valid and research_run_id:
        return "needs_research_report"
    if not report_valid:
        return "needs_research"
    if verified_claim_count == 0:
        return "needs_verified_research"
    return "blocked_by_missing_input"


def _next_action_hint(status: str, next_tools: list[str]) -> str:
    if status == "ready_to_fuse":
        return "Call build_recommendation_research_report with the current candidates and research_report."
    if status == "needs_candidates":
        return "Call search_books once with user_id to get fresh unsuppressed candidates."
    if status == "needs_research_report":
        return "Call build_research_report for the existing research run before fusion."
    if status == "needs_verified_research":
        return "Collect stronger source-backed evidence, admit it, and rebuild the research report."
    if status == "needs_research":
        return "Start a research run, collect approved sources, admit evidence, then build research-report-v1."
    if next_tools:
        return f"Next tool: {next_tools[0]}"
    return "No next action is available from the current workflow inputs."


def _candidate_suppressed(candidate: dict[str, Any]) -> bool:
    recommendation = dict(candidate.get("recommendation") or {})
    explanation = dict(candidate.get("recommendation_explanation") or {})
    return bool(
        recommendation.get("suppressed")
        or recommendation.get("suppression_reasons")
        or explanation.get("suppression_reasons")
    )


def _claim_dicts(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [dict(item) for item in value if isinstance(item, dict)]


def _research_run_id(
    *,
    report_payload: dict[str, Any],
    state: dict[str, Any],
) -> str:
    report_run_id = normalize_recommendation_text(report_payload.get("run_id"))
    if report_run_id:
        return report_run_id
    run = state.get("run")
    if isinstance(run, dict):
        return normalize_recommendation_text(run.get("id"))
    return normalize_recommendation_text(state.get("run_id"))


def _dedupe(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = normalize_recommendation_text(value)
        key = text.lower()
        if text and key not in seen:
            seen.add(key)
            result.append(text)
    return result
