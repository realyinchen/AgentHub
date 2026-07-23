from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from app.services.research.contracts import (
    EVIDENCE_QUALITIES,
    EVIDENCE_SOURCE_TYPES,
    normalize_research_token,
    normalize_text,
)
from app.services.research.observation_providers import ResearchObservation


RESEARCH_OBSERVATION_BATCH_CONTRACT_VERSION = "research-observation-batch-v1"


class ResearchSourceRecord(BaseModel):
    source_type: str = "web"
    source_title: str = ""
    source_url: str = ""
    claim: str = ""
    excerpt: str = ""
    quality: str = "unknown"
    relevance: int = Field(default=3, ge=1, le=5)
    metadata: dict[str, Any] = Field(default_factory=dict)


class RejectedResearchSource(BaseModel):
    source_type: str = "web"
    source_title: str = ""
    source_url: str = ""
    reason_codes: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ResearchObservationBatch(BaseModel):
    result_mode: str = "research_observation_batch"
    contract_version: str = RESEARCH_OBSERVATION_BATCH_CONTRACT_VERSION
    status: str = "ok"
    query: str = ""
    subquestion: str = ""
    observations: list[ResearchObservation] = Field(default_factory=list)
    rejected_sources: list[RejectedResearchSource] = Field(default_factory=list)
    source_count: int = 0
    observation_count: int = 0
    metadata: dict[str, Any] = Field(default_factory=dict)


def build_research_observation_batch(
    *,
    query: str = "",
    subquestion: str = "",
    sources: list[dict[str, Any] | ResearchObservation] | None = None,
    provider_source: str = "source_acquisition",
    metadata: dict[str, Any] | None = None,
) -> ResearchObservationBatch:
    """Normalize source records into app-owned research observations.

    This layer does not search, visit URLs, write Postgres state, or call
    provider transports. It only maps approved source records into
    ResearchObservation and rejects records that are not claim-bearing enough to
    enter the evidence pipeline.
    """

    observations: list[ResearchObservation] = []
    rejected: list[RejectedResearchSource] = []
    source_items = sources or []
    normalized_provider = normalize_text(provider_source) or "source_acquisition"

    for item in source_items:
        raw_payload = _raw_payload(item)
        record = _source_record(item)
        reason_codes = _rejection_reasons(record)
        if reason_codes:
            rejected.append(
                RejectedResearchSource(
                    source_type=record.source_type,
                    source_title=record.source_title,
                    source_url=record.source_url,
                    reason_codes=reason_codes,
                    metadata={
                        "provider_source": normalized_provider,
                        "provider_raw": raw_payload,
                    },
                )
            )
            continue

        observations.append(
            ResearchObservation(
                source_type=record.source_type,
                source_title=record.source_title,
                source_url=record.source_url,
                claim=record.claim,
                excerpt=record.excerpt,
                quality=record.quality,
                relevance=record.relevance,
                metadata={
                    **record.metadata,
                    "provider_source": record.metadata.get(
                        "provider_source",
                        normalized_provider,
                    ),
                    "provider_raw": record.metadata.get("provider_raw", raw_payload),
                    "source_acquisition": {
                        "contract_version": (
                            RESEARCH_OBSERVATION_BATCH_CONTRACT_VERSION
                        ),
                        "query": normalize_text(query),
                        "subquestion": normalize_text(subquestion),
                    },
                },
            )
        )

    status = "ok" if observations else "empty_result"
    return ResearchObservationBatch(
        status=status,
        query=normalize_text(query),
        subquestion=normalize_text(subquestion),
        observations=observations,
        rejected_sources=rejected,
        source_count=len(source_items),
        observation_count=len(observations),
        metadata={
            **(metadata or {}),
            "writes_research_state": False,
            "writes_long_term_memory": False,
            "writes_recommendation_events": False,
            "external_call": False,
            "provider_source": normalized_provider,
            "rejected_source_count": len(rejected),
        },
    )


def _source_record(
    item: dict[str, Any] | ResearchObservation,
) -> ResearchSourceRecord:
    if isinstance(item, ResearchObservation):
        payload = item.model_dump(mode="json")
    else:
        payload = dict(item or {})

    metadata = dict(payload.get("metadata") or {})
    source_type = _source_type(payload.get("source_type") or metadata.get("source_type"))
    source_title = normalize_text(
        payload.get("source_title")
        or payload.get("title")
        or payload.get("name")
        or metadata.get("source_title")
    )
    source_url = normalize_text(
        payload.get("source_url")
        or payload.get("url")
        or payload.get("href")
        or metadata.get("source_url")
    )
    claim = normalize_text(payload.get("claim") or metadata.get("claim"))
    excerpt = normalize_text(
        payload.get("excerpt")
        or payload.get("snippet")
        or payload.get("content")
        or payload.get("summary")
        or metadata.get("excerpt")
    )
    return ResearchSourceRecord(
        source_type=source_type,
        source_title=source_title,
        source_url=source_url,
        claim=claim,
        excerpt=excerpt,
        quality=_quality(payload.get("quality") or metadata.get("quality")),
        relevance=_relevance(payload.get("relevance") or payload.get("score")),
        metadata=metadata,
    )


def _rejection_reasons(record: ResearchSourceRecord) -> list[str]:
    reasons: list[str] = []
    if not record.claim:
        reasons.append("missing_claim")
    if not record.source_title and not record.source_url:
        reasons.append("missing_source_metadata")
    if not record.excerpt:
        reasons.append("missing_excerpt")
    return reasons


def _source_type(value: Any) -> str:
    token = normalize_research_token(value or "web")
    return token if token in EVIDENCE_SOURCE_TYPES else "other"


def _quality(value: Any) -> str:
    token = normalize_research_token(value or "unknown")
    return token if token in EVIDENCE_QUALITIES else "unknown"


def _relevance(value: Any) -> int:
    try:
        numeric = float(value if value is not None else 3)
    except (TypeError, ValueError):
        numeric = 3
    if numeric <= 1:
        numeric *= 5
    return max(1, min(5, round(numeric)))


def _raw_payload(item: dict[str, Any] | ResearchObservation) -> dict[str, Any]:
    if isinstance(item, ResearchObservation):
        return item.model_dump(mode="json")
    return dict(item or {})
