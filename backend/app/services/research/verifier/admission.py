from __future__ import annotations

from typing import Any
from uuid import UUID

from app.services.research.contracts import ResearchEvidence, clean_string_list
from app.services.research.verifier.contracts import (
    ClaimAdmissionDecision,
    ClaimForVerification,
    EvidenceReference,
    VerifierAdmissionInput,
    VerifierAdmissionResult,
)


QUALITY_RANK = {
    "unknown": 0,
    "low": 1,
    "medium": 2,
    "high": 3,
}


class ResearchVerifier:
    """Admits candidate claims only through app-owned evidence rules."""

    def verify(
        self,
        verifier_input: VerifierAdmissionInput | dict[str, Any],
    ) -> VerifierAdmissionResult:
        payload = VerifierAdmissionInput.model_validate(verifier_input)
        evidence_by_id = {
            item.id: item
            for item in payload.evidence
            if item.id is not None
        }
        min_sources = self._positive_int(
            payload.budget.get("min_sources_per_claim"),
            default=1,
        )
        required_quality = str(
            payload.budget.get("required_evidence_quality") or "medium"
        ).strip().lower()
        if required_quality not in QUALITY_RANK:
            required_quality = "medium"
        allow_uncertain = bool(payload.budget.get("allow_uncertain_final_answer"))
        require_within_budget = bool(payload.budget.get("require_within_budget"))

        decisions = [
            self._decide_claim(
                candidate=candidate,
                evidence_by_id=evidence_by_id,
                min_sources=min_sources,
                required_quality=required_quality,
            )
            for candidate in payload.candidate_claims
        ]
        admitted = [item for item in decisions if item.status == "admitted"]
        rejected = [item for item in decisions if item.status == "rejected"]
        uncertain = [item for item in decisions if item.status == "uncertain"]

        blocking_gaps = clean_string_list(payload.blocking_gaps)
        conflicts = clean_string_list(payload.conflicts)
        global_reason_codes: list[str] = []
        if blocking_gaps:
            global_reason_codes.append("blocking_gap")
        if conflicts:
            global_reason_codes.append("unresolved_conflict")
        if payload.stop_criteria and not (admitted or uncertain):
            blocking_gaps.append("Stop criteria are not satisfied by admitted evidence.")
            global_reason_codes.append("stop_criteria_not_met")
        if require_within_budget and self._budget_exceeded(payload):
            blocking_gaps.append("Verifier budget constraint is exceeded.")
            global_reason_codes.append("budget_exhausted")

        can_finalize_with_uncertainty = (
            allow_uncertain
            and bool(uncertain)
            and not conflicts
            and not self._budget_exceeded(payload, strict_only=True)
        )
        ready = (bool(admitted) and not blocking_gaps and not conflicts) or (
            can_finalize_with_uncertainty and not conflicts
        )
        if can_finalize_with_uncertainty:
            global_reason_codes.append("explicit_uncertainty")

        return VerifierAdmissionResult(
            run_id=payload.run_id,
            decisions=decisions,
            admitted_claims=admitted,
            rejected_claims=rejected,
            uncertain_claims=uncertain,
            blocking_gaps=blocking_gaps,
            conflicts=conflicts,
            ready_for_final_answer=ready,
            can_finalize_with_uncertainty=can_finalize_with_uncertainty,
            metadata={
                "claim_count": len(payload.candidate_claims),
                "evidence_count": len(evidence_by_id),
                "admitted_claim_count": len(admitted),
                "rejected_claim_count": len(rejected),
                "uncertain_claim_count": len(uncertain),
                "exhausted_query_count": len(payload.exhausted_queries),
                "stop_criteria": payload.stop_criteria,
                "stop_criteria_satisfied": bool(admitted or uncertain),
                "budget": payload.budget,
                "budget_exceeded": self._budget_exceeded(payload),
                "reason_codes": self._unique_reason_codes(global_reason_codes),
            },
        )

    def _decide_claim(
        self,
        *,
        candidate: ClaimForVerification,
        evidence_by_id: dict[UUID, ResearchEvidence],
        min_sources: int,
        required_quality: str,
    ) -> ClaimAdmissionDecision:
        reason_codes: list[str] = []
        supporting = [
            evidence_by_id[evidence_id]
            for evidence_id in candidate.evidence_ids
            if evidence_id in evidence_by_id
        ]
        missing_ids = [
            evidence_id
            for evidence_id in candidate.evidence_ids
            if evidence_id not in evidence_by_id
        ]
        if not candidate.evidence_ids:
            return self._decision(
                candidate,
                status="rejected",
                evidence=[],
                reason_codes=["missing_evidence"],
                explanation="Candidate claim has no supporting evidence IDs.",
            )
        if missing_ids:
            return self._decision(
                candidate,
                status="rejected",
                evidence=supporting,
                reason_codes=["unknown_evidence"],
                explanation="Candidate claim references evidence not present in research state.",
            )
        if len(supporting) < min_sources:
            reason_codes.append("insufficient_sources")

        if any(not self._has_source_metadata(item) for item in supporting):
            reason_codes.append("missing_source_metadata")

        max_quality = self._max_quality(supporting, fallback=candidate.quality)
        if max_quality == "unknown":
            reason_codes.append("unknown_quality_evidence")
        elif QUALITY_RANK[max_quality] < QUALITY_RANK[required_quality]:
            reason_codes.append("low_quality_evidence")

        if reason_codes:
            return self._decision(
                candidate,
                status="uncertain",
                evidence=supporting,
                reason_codes=reason_codes,
                explanation="Candidate claim is source-backed but not strong enough for verified admission.",
                quality=max_quality,
            )

        return self._decision(
            candidate,
            status="admitted",
            evidence=supporting,
            reason_codes=["supported_by_evidence"],
            explanation="Candidate claim has sufficient supporting evidence.",
            quality=max_quality,
        )

    def _decision(
        self,
        candidate: ClaimForVerification,
        *,
        status: str,
        evidence: list[ResearchEvidence],
        reason_codes: list[str],
        explanation: str,
        quality: str | None = None,
    ) -> ClaimAdmissionDecision:
        references = [
            EvidenceReference(
                id=item.id,
                source_type=item.source_type,
                source_title=item.source_title,
                source_url=item.source_url,
                quality=item.quality,
                relevance=item.relevance,
            )
            for item in evidence
            if item.id is not None
        ]
        return ClaimAdmissionDecision(
            claim=candidate.claim,
            status=status,
            evidence_ids=[item.id for item in evidence if item.id is not None],
            evidence=references,
            quality=quality or self._max_quality(evidence, fallback=candidate.quality),
            reason_codes=reason_codes,
            explanation=explanation,
            metadata=candidate.metadata,
        )

    def _max_quality(
        self,
        evidence: list[ResearchEvidence],
        *,
        fallback: str,
    ) -> str:
        quality = fallback if fallback in QUALITY_RANK else "unknown"
        for item in evidence:
            if QUALITY_RANK[item.quality] > QUALITY_RANK[quality]:
                quality = item.quality
        return quality

    def _has_source_metadata(self, evidence: ResearchEvidence) -> bool:
        return bool(evidence.source_title.strip() or evidence.source_url.strip())

    def _positive_int(self, value: Any, *, default: int) -> int:
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            return default
        return parsed if parsed > 0 else default

    def _budget_exceeded(
        self,
        payload: VerifierAdmissionInput,
        *,
        strict_only: bool = False,
    ) -> bool:
        if strict_only and not payload.budget.get("require_within_budget"):
            return False
        max_sources = payload.budget.get("max_sources")
        if max_sources is None:
            return False
        try:
            return len(payload.evidence) > int(max_sources)
        except (TypeError, ValueError):
            return False

    def _unique_reason_codes(self, values: list[str]) -> list[str]:
        seen: set[str] = set()
        cleaned: list[str] = []
        for value in values:
            if value not in seen:
                seen.add(value)
                cleaned.append(value)
        return cleaned
