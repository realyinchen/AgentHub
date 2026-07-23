from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from app.services.research.contracts import ResearchEvidence, normalize_text


RESEARCH_EVIDENCE_ADMISSION_CONTRACT_VERSION = "research-evidence-admission-v1"


class ResearchEvidenceAdmissionResult(BaseModel):
    result_mode: str = "research_evidence_admission"
    contract_version: str = RESEARCH_EVIDENCE_ADMISSION_CONTRACT_VERSION
    status: str
    allowed: bool
    reason_codes: list[str] = Field(default_factory=list)
    warning_codes: list[str] = Field(default_factory=list)
    evidence: ResearchEvidence
    metadata: dict[str, Any] = Field(default_factory=dict)


def admit_research_evidence(evidence: ResearchEvidence) -> ResearchEvidenceAdmissionResult:
    """Decide whether extracted source material can enter Evidence Store.

    Evidence Store may keep weak evidence so the verifier can label uncertainty,
    but it must not store untraceable material that lacks a claim, excerpt, or
    source metadata.
    """

    normalized = ResearchEvidence.model_validate(evidence)
    reason_codes = _rejection_reasons(normalized)
    warning_codes = _warning_codes(normalized)
    allowed = not reason_codes
    status = "accepted" if allowed and not warning_codes else "accepted_with_warnings"
    if not allowed:
        status = "rejected"

    return ResearchEvidenceAdmissionResult(
        status=status,
        allowed=allowed,
        reason_codes=reason_codes,
        warning_codes=warning_codes,
        evidence=normalized,
        metadata={
            "writes_evidence": allowed,
            "writes_long_term_memory": False,
            "writes_recommendation_events": False,
            "external_call": False,
        },
    )


def attach_evidence_admission_metadata(
    evidence: ResearchEvidence,
    admission: ResearchEvidenceAdmissionResult,
) -> ResearchEvidence:
    metadata = dict(evidence.metadata or {})
    metadata["evidence_admission"] = {
        "contract_version": admission.contract_version,
        "status": admission.status,
        "allowed": admission.allowed,
        "reason_codes": admission.reason_codes,
        "warning_codes": admission.warning_codes,
    }
    return evidence.model_copy(update={"metadata": metadata})


def _rejection_reasons(evidence: ResearchEvidence) -> list[str]:
    reasons: list[str] = []
    if not normalize_text(evidence.claim):
        reasons.append("missing_claim")
    if not normalize_text(evidence.excerpt):
        reasons.append("missing_excerpt")
    if not normalize_text(evidence.source_title) and not normalize_text(
        evidence.source_url
    ):
        reasons.append("missing_source_metadata")
    return reasons


def _warning_codes(evidence: ResearchEvidence) -> list[str]:
    warnings: list[str] = []
    if evidence.quality == "unknown":
        warnings.append("unknown_quality_evidence")
    elif evidence.quality == "low":
        warnings.append("low_quality_evidence")
    if evidence.relevance <= 2:
        warnings.append("low_relevance_evidence")
    if normalize_text(evidence.source_title) and not normalize_text(evidence.source_url):
        warnings.append("missing_source_url")
    return warnings
