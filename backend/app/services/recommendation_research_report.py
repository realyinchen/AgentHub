from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, Field

from app.services.recommendation_signals import normalize_recommendation_text
from app.services.research.report import RESEARCH_REPORT_CONTRACT_VERSION


RECOMMENDATION_RESEARCH_REPORT_CONTRACT_VERSION = (
    "recommendation-research-report-v1"
)
MAX_RECOMMENDATION_RESEARCH_CANDIDATES = 10
MAX_RESEARCH_SUPPORT_CLAIMS_PER_CANDIDATE = 5
_WORD_RE = re.compile(r"[\w\u4e00-\u9fff]+", re.IGNORECASE)


class RecommendationResearchClaimLink(BaseModel):
    claim: str
    source_title: str = ""
    source_url: str = ""
    source_type: str = ""
    quality: str = "unknown"
    relevance: int = 3
    evidence_ids: list[str] = Field(default_factory=list)
    reason: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)


class RecommendationResearchCandidate(BaseModel):
    rank: int
    book_id: str = ""
    title: str
    authors: list[str] = Field(default_factory=list)
    summary: str = ""
    rating: float | None = None
    source_name: str = ""
    source_url: str = ""
    recommendation_score: float | None = None
    candidate_source: dict[str, Any] = Field(default_factory=dict)
    recommendation_explanation: dict[str, Any] = Field(default_factory=dict)
    personalization_reasons: list[str] = Field(default_factory=list)
    research_support: list[RecommendationResearchClaimLink] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    supported_by_verified_research: bool = False
    suppressed: bool = False
    suppression_reasons: list[str] = Field(default_factory=list)
    fit_summary: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)


class RecommendationResearchReport(BaseModel):
    result_mode: str = "recommendation_research_report"
    contract_version: str = RECOMMENDATION_RESEARCH_REPORT_CONTRACT_VERSION
    status: str
    query: str = ""
    research_run_id: str = ""
    research_report_status: str = ""
    research_report_contract_version: str = ""
    candidates: list[RecommendationResearchCandidate] = Field(default_factory=list)
    recommended_candidates: list[RecommendationResearchCandidate] = Field(default_factory=list)
    suppressed_candidates: list[RecommendationResearchCandidate] = Field(default_factory=list)
    unsupported_candidates: list[RecommendationResearchCandidate] = Field(default_factory=list)
    candidate_count: int = 0
    supported_count: int = 0
    suppressed_count: int = 0
    verified_claim_count: int = 0
    limitations: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


def build_recommendation_research_report(
    *,
    query: str = "",
    candidates: list[dict[str, Any]] | None = None,
    research_report: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
) -> RecommendationResearchReport:
    """Fuse ordinary recommendation candidates with a verified research report.

    This is a read-only projector. It does not search books, run research,
    admit evidence, write long-term memory, write recommendation events, or call
    provider transports. Only `verified_claims` from `research-report-v1` are
    allowed to support recommendation candidates.
    """

    normalized_query = normalize_recommendation_text(query)
    report_payload = dict(research_report or {})
    verified_claims = _claim_dicts(report_payload.get("verified_claims"))
    uncertain_claims = _claim_dicts(report_payload.get("uncertain_claims"))
    rejected_claims = _claim_dicts(report_payload.get("rejected_claims"))
    sources = _source_dicts(report_payload.get("sources"))
    source_by_claim = {
        normalize_recommendation_text(source.get("claim")).lower(): source
        for source in sources
        if normalize_recommendation_text(source.get("claim"))
    }

    projected_candidates: list[RecommendationResearchCandidate] = []
    for index, candidate in enumerate(
        list(candidates or [])[:MAX_RECOMMENDATION_RESEARCH_CANDIDATES],
        start=1,
    ):
        projected_candidates.append(
            _project_candidate(
                rank=index,
                candidate=dict(candidate or {}),
                verified_claims=verified_claims,
                uncertain_claims=uncertain_claims,
                rejected_claims=rejected_claims,
                source_by_claim=source_by_claim,
            )
        )

    supported = [
        candidate
        for candidate in projected_candidates
        if candidate.supported_by_verified_research and not candidate.suppressed
    ]
    unsupported = [
        candidate
        for candidate in projected_candidates
        if not candidate.supported_by_verified_research and not candidate.suppressed
    ]
    suppressed = [candidate for candidate in projected_candidates if candidate.suppressed]
    supported.sort(
        key=lambda item: (
            len(item.research_support),
            item.recommendation_score if item.recommendation_score is not None else 0,
            -item.rank,
        ),
        reverse=True,
    )

    limitations = _report_limitations(
        report_payload=report_payload,
        verified_claims=verified_claims,
        unsupported=unsupported,
        uncertain_claims=uncertain_claims,
        rejected_claims=rejected_claims,
    )
    return RecommendationResearchReport(
        status=_result_status(projected_candidates, supported, verified_claims),
        query=normalized_query,
        research_run_id=normalize_recommendation_text(report_payload.get("run_id")),
        research_report_status=normalize_recommendation_text(
            report_payload.get("report_status")
        ),
        research_report_contract_version=normalize_recommendation_text(
            report_payload.get("contract_version")
        ),
        candidates=projected_candidates,
        recommended_candidates=supported,
        suppressed_candidates=suppressed,
        unsupported_candidates=unsupported,
        candidate_count=len(projected_candidates),
        supported_count=len(supported),
        suppressed_count=len(suppressed),
        verified_claim_count=len(verified_claims),
        limitations=limitations,
        metadata={
            **(metadata or {}),
            "writes_research_state": False,
            "writes_evidence": False,
            "writes_long_term_memory": False,
            "writes_recommendation_events": False,
            "external_call": False,
            "uses_verified_claims_only": True,
            "research_report_contract_expected": RESEARCH_REPORT_CONTRACT_VERSION,
            "research_report_contract_seen": normalize_recommendation_text(
                report_payload.get("contract_version")
            ),
            "uncertain_claim_count": len(uncertain_claims),
            "rejected_claim_count": len(rejected_claims),
        },
    )


def _project_candidate(
    *,
    rank: int,
    candidate: dict[str, Any],
    verified_claims: list[dict[str, Any]],
    uncertain_claims: list[dict[str, Any]],
    rejected_claims: list[dict[str, Any]],
    source_by_claim: dict[str, dict[str, Any]],
) -> RecommendationResearchCandidate:
    title = normalize_recommendation_text(candidate.get("title"))
    recommendation = dict(candidate.get("recommendation") or {})
    explanation = dict(candidate.get("recommendation_explanation") or {})
    recommendation_metadata = dict(recommendation.get("metadata") or {})
    research_support = _research_support_for_candidate(
        candidate=candidate,
        verified_claims=verified_claims,
        source_by_claim=source_by_claim,
    )
    suppression_reasons = _clean_strings(
        [
            *(recommendation.get("suppression_reasons") or []),
            *(explanation.get("suppression_reasons") or []),
        ]
    )
    suppressed = bool(recommendation.get("suppressed")) or bool(suppression_reasons)
    personalization_reasons = _clean_strings(
        [
            *(recommendation.get("positive_reasons") or []),
            *(explanation.get("positive_reasons") or []),
        ]
    )[:8]
    limitations = _candidate_limitations(
        title=title,
        research_support=research_support,
        uncertain_claims=uncertain_claims,
        rejected_claims=rejected_claims,
        suppressed=suppressed,
        suppression_reasons=suppression_reasons,
    )
    score = recommendation.get("score")
    if score is None:
        score = explanation.get("score")
    return RecommendationResearchCandidate(
        rank=rank,
        book_id=normalize_recommendation_text(candidate.get("id")),
        title=title or f"candidate_{rank}",
        authors=_clean_strings(candidate.get("authors") or []),
        summary=normalize_recommendation_text(candidate.get("summary")),
        rating=_float_or_none(candidate.get("rating")),
        source_name=normalize_recommendation_text(candidate.get("source_name")),
        source_url=normalize_recommendation_text(candidate.get("source_url")),
        recommendation_score=_float_or_none(score),
        candidate_source=dict(candidate.get("candidate_source") or {}),
        recommendation_explanation=explanation,
        personalization_reasons=personalization_reasons,
        research_support=research_support,
        limitations=limitations,
        supported_by_verified_research=bool(research_support),
        suppressed=suppressed,
        suppression_reasons=suppression_reasons,
        fit_summary=_fit_summary(
            title=title,
            personalization_reasons=personalization_reasons,
            support=research_support,
            suppressed=suppressed,
        ),
        metadata={
            "source_result_mode": normalize_recommendation_text(
                candidate.get("result_mode")
            ),
            "recommendation_contract": normalize_recommendation_text(
                recommendation_metadata.get("contract_version")
            ),
            "explanation_contract": normalize_recommendation_text(
                explanation.get("contract_version")
            ),
        },
    )


def _research_support_for_candidate(
    *,
    candidate: dict[str, Any],
    verified_claims: list[dict[str, Any]],
    source_by_claim: dict[str, dict[str, Any]],
) -> list[RecommendationResearchClaimLink]:
    support: list[RecommendationResearchClaimLink] = []
    candidate_text = _candidate_text(candidate)
    for claim in verified_claims:
        claim_text = normalize_recommendation_text(claim.get("claim"))
        if not claim_text or not _claim_matches_candidate(claim_text, candidate_text):
            continue
        source = source_by_claim.get(claim_text.lower(), {})
        support.append(
            RecommendationResearchClaimLink(
                claim=claim_text,
                source_title=normalize_recommendation_text(source.get("source_title")),
                source_url=normalize_recommendation_text(source.get("source_url")),
                source_type=normalize_recommendation_text(source.get("source_type")),
                quality=normalize_recommendation_text(source.get("quality")) or "unknown",
                relevance=_int_or_default(source.get("relevance"), 3),
                evidence_ids=_clean_strings(claim.get("evidence_ids") or []),
                reason="verified research claim mentions this candidate",
                metadata={
                    "reason_codes": claim.get("reason_codes") or [],
                    "confidence": claim.get("confidence"),
                },
            )
        )
        if len(support) >= MAX_RESEARCH_SUPPORT_CLAIMS_PER_CANDIDATE:
            break
    return support


def _claim_matches_candidate(claim: str, candidate_text: str) -> bool:
    if not claim or not candidate_text:
        return False
    claim_lower = claim.lower()
    candidate_lower = candidate_text.lower()
    title = candidate_lower.split("\n", 1)[0].strip()
    if title and title in claim_lower:
        return True
    title_terms = _terms(title)
    if title_terms and sum(1 for term in title_terms if term in claim_lower) >= min(
        2,
        len(title_terms),
    ):
        return True
    claim_terms = set(_terms(claim_lower))
    candidate_terms = set(_terms(candidate_lower))
    if not claim_terms or not candidate_terms:
        return False
    return len(claim_terms.intersection(candidate_terms)) >= 3


def _candidate_text(candidate: dict[str, Any]) -> str:
    explanation = dict(candidate.get("recommendation_explanation") or {})
    recommendation = dict(candidate.get("recommendation") or {})
    parts = [
        normalize_recommendation_text(candidate.get("title")),
        " ".join(_clean_strings(candidate.get("authors") or [])),
        normalize_recommendation_text(candidate.get("summary")),
        normalize_recommendation_text(explanation.get("summary")),
        " ".join(_clean_strings(explanation.get("positive_reasons") or [])),
        " ".join(_clean_strings(recommendation.get("positive_reasons") or [])),
    ]
    return "\n".join(part for part in parts if part)


def _candidate_limitations(
    *,
    title: str,
    research_support: list[RecommendationResearchClaimLink],
    uncertain_claims: list[dict[str, Any]],
    rejected_claims: list[dict[str, Any]],
    suppressed: bool,
    suppression_reasons: list[str],
) -> list[str]:
    limitations: list[str] = []
    if not research_support:
        limitations.append("no_verified_research_claim_matched_candidate")
    if _claims_mention_title(uncertain_claims, title):
        limitations.append("candidate_has_uncertain_research_claims")
    if _claims_mention_title(rejected_claims, title):
        limitations.append("candidate_has_rejected_research_claims")
    if suppressed:
        limitations.append(
            "candidate_suppressed:"
            + (", ".join(suppression_reasons) if suppression_reasons else "unknown")
        )
    return limitations


def _claims_mention_title(claims: list[dict[str, Any]], title: str) -> bool:
    normalized_title = normalize_recommendation_text(title).lower()
    if not normalized_title:
        return False
    return any(
        normalized_title in normalize_recommendation_text(claim.get("claim")).lower()
        for claim in claims
    )


def _fit_summary(
    *,
    title: str,
    personalization_reasons: list[str],
    support: list[RecommendationResearchClaimLink],
    suppressed: bool,
) -> str:
    if suppressed:
        return f"{title} remains suppressed and should not be presented as a fresh recommendation."
    parts = []
    if personalization_reasons:
        parts.append(f"personal fit: {personalization_reasons[0]}")
    if support:
        parts.append(f"research support: {support[0].claim}")
    if not parts:
        parts.append("no verified research support matched this candidate")
    return "; ".join(parts)


def _report_limitations(
    *,
    report_payload: dict[str, Any],
    verified_claims: list[dict[str, Any]],
    unsupported: list[RecommendationResearchCandidate],
    uncertain_claims: list[dict[str, Any]],
    rejected_claims: list[dict[str, Any]],
) -> list[str]:
    limitations: list[str] = []
    if normalize_recommendation_text(report_payload.get("contract_version")) != (
        RESEARCH_REPORT_CONTRACT_VERSION
    ):
        limitations.append("research_report_contract_unverified")
    if not verified_claims:
        limitations.append("no_verified_research_claims")
    if unsupported:
        limitations.append("some_candidates_lack_verified_research_support")
    if uncertain_claims:
        limitations.append("uncertain_research_claims_omitted_from_support")
    if rejected_claims:
        limitations.append("rejected_research_claims_omitted_from_support")
    return limitations


def _result_status(
    candidates: list[RecommendationResearchCandidate],
    supported: list[RecommendationResearchCandidate],
    verified_claims: list[dict[str, Any]],
) -> str:
    if not candidates:
        return "empty_result"
    if supported:
        return "ok"
    if not verified_claims:
        return "needs_verified_research"
    return "no_candidate_supported_by_research"


def _claim_dicts(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [dict(item) for item in value if isinstance(item, dict)]


def _source_dicts(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [dict(item) for item in value if isinstance(item, dict)]


def _clean_strings(values: list[Any]) -> list[str]:
    cleaned: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = normalize_recommendation_text(value)
        key = text.lower()
        if text and key not in seen:
            seen.add(key)
            cleaned.append(text)
    return cleaned


def _terms(text: str) -> list[str]:
    return [
        term
        for term in _WORD_RE.findall(text.lower())
        if len(term) >= 2
        and term
        not in {
            "book",
            "novel",
            "novels",
            "story",
            "stories",
            "the",
            "and",
        }
    ]


def _float_or_none(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _int_or_default(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default
