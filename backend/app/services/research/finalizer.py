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
    return finalize_research_answer_from_report(report)


def finalize_research_answer_from_report(report: ResearchReport) -> ResearchFinalAnswer:
    verified = list(report.verified_claims)
    uncertain = list(report.uncertain_claims)
    rejected = list(report.rejected_claims)
    limitations = _limitations(report)
    answer_status = _answer_status(report, verified)
    return ResearchFinalAnswer(
        user_id=report.user_id,
        run_id=report.run_id,
        objective=report.objective,
        report_status=report.report_status,
        answer_status=answer_status,
        answer=_answer_text(report, verified, limitations),
        verified_claims=verified,
        omitted_uncertain_claims=uncertain,
        omitted_rejected_claims=rejected,
        limitations=limitations,
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
        },
    )


def _answer_status(
    report: ResearchReport,
    verified: list[ClaimAdmissionDecision],
) -> str:
    if report.verification.ready_for_final_answer and verified:
        return "verified"
    if verified:
        return "partial_with_limitations"
    if report.verification.can_finalize_with_uncertainty:
        return "uncertain_no_verified_claims"
    return "blocked_no_verified_claims"


def _answer_text(
    report: ResearchReport,
    verified: list[ClaimAdmissionDecision],
    limitations: list[str],
) -> str:
    if not verified:
        lines = [
            f"I cannot give a verified answer for this research objective yet: {report.objective}",
        ]
        if limitations:
            lines.append("Key limitations:")
            lines.extend(f"- {item}" for item in limitations[:5])
        return "\n".join(lines)

    lines = [
        f"Based on verified source-backed evidence for: {report.objective}",
    ]
    for index, claim in enumerate(verified, start=1):
        lines.append(f"{index}. {claim.claim}")
    if limitations:
        lines.append("Limitations:")
        lines.extend(f"- {item}" for item in limitations[:5])
    return "\n".join(lines)


def _limitations(report: ResearchReport) -> list[str]:
    limitations: list[str] = []
    if report.uncertain_claims:
        limitations.append(
            f"{len(report.uncertain_claims)} uncertain claim(s) were not used as final facts."
        )
    if report.rejected_claims:
        limitations.append(
            f"{len(report.rejected_claims)} rejected claim(s) were excluded."
        )
    limitations.extend(f"Open gap: {gap}" for gap in report.gaps[:3])
    limitations.extend(f"Conflict: {conflict}" for conflict in report.conflicts[:3])
    if report.memory_context.constraints:
        limitations.append("CurrentMemory was used only as personal context, not evidence.")
    return limitations


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
