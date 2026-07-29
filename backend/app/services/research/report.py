from __future__ import annotations

from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field

from app.services.memory import get_memory_orchestrator
from app.services.research.contracts import ResearchEvidence, ResearchStateResult
from app.services.research.orchestrator import get_research_orchestrator
from app.services.research.verifier import (
    ClaimAdmissionDecision,
    ClaimForVerification,
    ResearchVerifier,
    VerifierAdmissionInput,
    VerifierAdmissionResult,
)


RESEARCH_REPORT_CONTRACT_VERSION = "research-report-v1"


class ResearchReportSource(BaseModel):
    evidence_id: UUID
    source_type: str = "web"
    source_title: str = ""
    source_url: str = ""
    published_date: str = ""
    quality: str = "unknown"
    relevance: int = 3
    claim: str = ""


class ResearchReportMemoryContext(BaseModel):
    memory_ids: list[str] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)


class ResearchReport(BaseModel):
    result_mode: str = "research_report"
    contract_version: str = RESEARCH_REPORT_CONTRACT_VERSION
    run_id: UUID
    user_id: UUID
    objective: str
    run_status: str
    report_status: str
    final_answer: str = ""
    verified_claims: list[ClaimAdmissionDecision] = Field(default_factory=list)
    uncertain_claims: list[ClaimAdmissionDecision] = Field(default_factory=list)
    rejected_claims: list[ClaimAdmissionDecision] = Field(default_factory=list)
    sources: list[ResearchReportSource] = Field(default_factory=list)
    gaps: list[str] = Field(default_factory=list)
    conflicts: list[str] = Field(default_factory=list)
    exhausted_queries: list[str] = Field(default_factory=list)
    next_actions: list[str] = Field(default_factory=list)
    memory_context: ResearchReportMemoryContext = Field(
        default_factory=ResearchReportMemoryContext
    )
    verification: VerifierAdmissionResult
    metadata: dict[str, Any] = Field(default_factory=dict)


async def build_research_report(
    *,
    user_id: UUID,
    run_id: UUID,
    limit_steps: int = 100,
    limit_evidence: int = 100,
) -> ResearchReport:
    research_state = await get_research_orchestrator().inspect_research_state(
        user_id=user_id,
        run_id=run_id,
        limit_steps=limit_steps,
        limit_evidence=limit_evidence,
    )
    memory_context = await _build_memory_context(user_id)
    return build_research_report_from_state(
        research_state,
        memory_context=memory_context,
    )


def build_research_report_from_state(
    research_state: ResearchStateResult,
    *,
    memory_context: ResearchReportMemoryContext | None = None,
) -> ResearchReport:
    run_id = research_state.run.id
    if run_id is None:
        raise ValueError("research run id is required")

    verifier = ResearchVerifier()
    candidate_claims = _candidate_claims_from_evidence(research_state.evidence)
    verification = verifier.verify(
        VerifierAdmissionInput(
            run_id=run_id,
            objective=research_state.run.objective,
            candidate_claims=candidate_claims,
            evidence=research_state.evidence,
            blocking_gaps=research_state.state.gaps,
            conflicts=research_state.state.conflicts,
            exhausted_queries=research_state.state.exhausted_queries,
            budget=research_state.state.budget,
            stop_criteria=research_state.state.stop_criteria,
            metadata={"source": "research_report_projector"},
        )
    )
    report_status = _report_status(research_state, verification)
    return ResearchReport(
        run_id=run_id,
        user_id=research_state.run.user_id,
        objective=research_state.run.objective,
        run_status=research_state.run.status,
        report_status=report_status,
        final_answer=_final_answer(
            objective=research_state.run.objective,
            verification=verification,
            gaps=research_state.state.gaps,
            conflicts=research_state.state.conflicts,
        ),
        verified_claims=verification.admitted_claims,
        uncertain_claims=verification.uncertain_claims,
        rejected_claims=verification.rejected_claims,
        sources=_sources_from_evidence(research_state.evidence),
        gaps=research_state.state.gaps,
        conflicts=research_state.state.conflicts,
        exhausted_queries=research_state.state.exhausted_queries,
        next_actions=research_state.state.next_actions,
        memory_context=memory_context or ResearchReportMemoryContext(),
        verification=verification,
        metadata={
            "step_count": len(research_state.steps),
            "evidence_count": len(research_state.evidence),
            "provider_sources": research_state.provider_sources,
            "ready_for_final_answer": verification.ready_for_final_answer,
            "can_finalize_with_uncertainty": (
                verification.can_finalize_with_uncertainty
            ),
        },
    )


async def _build_memory_context(user_id: UUID) -> ResearchReportMemoryContext:
    try:
        current = await get_memory_orchestrator().list_current_memories(
            user_id=user_id,
            limit=20,
        )
    except Exception:
        return ResearchReportMemoryContext()
    constraints = []
    memory_ids = []
    for memory in current.memories:
        if memory.id is not None:
            memory_ids.append(str(memory.id))
        constraints.append(
            f"{memory.type}:{memory.subject}:{memory.polarity}:{memory.value}"
        )
    return ResearchReportMemoryContext(
        memory_ids=memory_ids,
        constraints=constraints,
    )


def _candidate_claims_from_evidence(
    evidence: list[ResearchEvidence],
) -> list[ClaimForVerification]:
    claims: list[ClaimForVerification] = []
    for item in evidence:
        if item.id is None:
            continue
        claims.append(
            ClaimForVerification(
                claim=item.claim,
                evidence_ids=[item.id],
                quality=item.quality,
                metadata={
                    "source_title": item.source_title,
                    "source_url": item.source_url,
                    "source_type": item.source_type,
                },
            )
        )
    return claims


def _sources_from_evidence(
    evidence: list[ResearchEvidence],
) -> list[ResearchReportSource]:
    sources: list[ResearchReportSource] = []
    seen: set[str] = set()
    for item in evidence:
        if item.id is None:
            continue
        key = str(item.id)
        if key in seen:
            continue
        seen.add(key)
        sources.append(
            ResearchReportSource(
                evidence_id=item.id,
                source_type=item.source_type,
                source_title=item.source_title,
                source_url=item.source_url,
                published_date=_evidence_published_date(item),
                quality=item.quality,
                relevance=item.relevance,
                claim=item.claim,
            )
        )
    return sources


def _evidence_published_date(evidence: ResearchEvidence) -> str:
    metadata = evidence.metadata if isinstance(evidence.metadata, dict) else {}
    source_record = metadata.get("source_record")
    source_record = source_record if isinstance(source_record, dict) else {}
    record_metadata = source_record.get("metadata")
    record_metadata = record_metadata if isinstance(record_metadata, dict) else {}
    return str(
        metadata.get("published_date")
        or source_record.get("published_date")
        or record_metadata.get("published_date")
        or ""
    ).strip()


def _report_status(
    research_state: ResearchStateResult,
    verification: VerifierAdmissionResult,
) -> str:
    if verification.ready_for_final_answer and verification.admitted_claims:
        return "verified"
    if verification.can_finalize_with_uncertainty:
        return "uncertain_final"
    if verification.admitted_claims:
        return "partial_with_gaps"
    if verification.uncertain_claims:
        return "needs_stronger_evidence"
    if research_state.state.gaps or research_state.state.next_actions:
        return "needs_more_research"
    return "no_verified_claims"


def _final_answer(
    *,
    objective: str,
    verification: VerifierAdmissionResult,
    gaps: list[str],
    conflicts: list[str],
) -> str:
    zh = any("\u4e00" <= char <= "\u9fff" for char in objective)
    lines = [f"{'研究目标' if zh else 'Research objective'}：{objective}"]
    if verification.admitted_claims:
        lines.append("已准入证据：" if zh else "Admitted evidence:")
        for index, claim in enumerate(
            verification.admitted_claims[:5],
            start=1,
        ):
            lines.append(f"{index}. {_bounded(claim.claim, 240)}")
    else:
        lines.append(
            "目前没有通过发布质量检查的证据。"
            if zh
            else "No evidence has passed publication checks yet."
        )

    if verification.uncertain_claims:
        lines.append("待补强证据：" if zh else "Evidence needing support:")
        for claim in verification.uncertain_claims[:5]:
            reasons = ", ".join(claim.reason_codes) or "uncertain"
            lines.append(f"- {_bounded(claim.claim, 180)} ({reasons})")
    if gaps:
        lines.append("待补问题：" if zh else "Open gaps:")
        lines.extend(f"- {gap}" for gap in gaps[:5])
    if conflicts:
        lines.append("未解决冲突：" if zh else "Unresolved conflicts:")
        lines.extend(f"- {conflict}" for conflict in conflicts[:5])
    return "\n".join(lines)


def _bounded(value: str, limit: int) -> str:
    text = " ".join(str(value or "").split()).strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"
