from __future__ import annotations

from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field

from app.services.research.report import (
    ResearchReport,
    ResearchReportSource,
    build_research_report,
)
from app.services.research.verifier import ClaimAdmissionDecision
from app.services.research.publication import (
    PublishedResearchAnswer,
    publish_research_answer,
    synthesize_research_report_deterministic,
)


RESEARCH_FINAL_ANSWER_CONTRACT_VERSION = "research-final-answer-v1"


class ResearchFinalAnswer(BaseModel):
    result_mode: str = "research_final_answer"
    contract_version: str = RESEARCH_FINAL_ANSWER_CONTRACT_VERSION
    user_id: UUID
    run_id: UUID
    objective: str
    report_status: str
    answer_status: str
    answer: str
    verified_claims: list[ClaimAdmissionDecision] = Field(default_factory=list)
    omitted_uncertain_claims: list[ClaimAdmissionDecision] = Field(default_factory=list)
    omitted_rejected_claims: list[ClaimAdmissionDecision] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    sources: list[ResearchReportSource] = Field(default_factory=list)
    ready_for_final_answer: bool = False
    can_finalize_with_uncertainty: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)


async def finalize_research_answer(
    *,
    user_id: UUID,
    run_id: UUID,
    limit_steps: int = 100,
    limit_evidence: int = 100,
) -> ResearchFinalAnswer:
    report = await build_research_report(
        user_id=user_id,
        run_id=run_id,
        limit_steps=limit_steps,
        limit_evidence=limit_evidence,
    )
    synthesis = synthesize_research_report_deterministic(report)
    published = publish_research_answer(report, synthesis)
    return _legacy_result(report, published)


def finalize_research_answer_from_report(report: ResearchReport) -> ResearchFinalAnswer:
    synthesis = synthesize_research_report_deterministic(report)
    published = publish_research_answer(report, synthesis)
    return _legacy_result(report, published)


def _legacy_result(
    report: ResearchReport,
    published: PublishedResearchAnswer,
) -> ResearchFinalAnswer:
    verified = list(report.verified_claims)
    uncertain = list(report.uncertain_claims)
    rejected = list(report.rejected_claims)
    return ResearchFinalAnswer(
        user_id=report.user_id,
        run_id=report.run_id,
        objective=report.objective,
        report_status=report.report_status,
        answer_status=published.answer_status,
        answer=published.answer,
        verified_claims=verified,
        omitted_uncertain_claims=uncertain,
        omitted_rejected_claims=rejected,
        limitations=published.limitations,
        sources=_sources_for_verified_claims(report, verified),
        ready_for_final_answer=report.verification.ready_for_final_answer,
        can_finalize_with_uncertainty=(
            report.verification.can_finalize_with_uncertainty
        ),
        metadata={
            "source_report_contract_version": report.contract_version,
            "source_report_status": report.report_status,
            "verified_claim_count": len(verified),
            "omitted_uncertain_claim_count": len(uncertain),
            "omitted_rejected_claim_count": len(rejected),
            "writes_research_state": False,
            "writes_evidence": False,
            "writes_long_term_memory": False,
            "writes_recommendation_events": False,
            "external_call": False,
            "published_answer_contract_version": published.contract_version,
        },
    )


def _sources_for_verified_claims(
    report: ResearchReport,
    verified: list[ClaimAdmissionDecision],
) -> list[ResearchReportSource]:
    verified_evidence_ids = {
        str(evidence_id)
        for claim in verified
        for evidence_id in claim.evidence_ids
    }
    if not verified_evidence_ids:
        return []
    return [
        source
        for source in report.sources
        if str(source.evidence_id) in verified_evidence_ids
    ]
