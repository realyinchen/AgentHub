from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, Field

from app.services.research.contracts import (
    EVIDENCE_QUALITIES,
    EVIDENCE_SOURCE_TYPES,
    normalize_research_token,
    normalize_text,
)
from app.services.research.source_acquisition import (
    ResearchObservationBatch,
    ResearchSourceRecord,
    build_research_observation_batch,
)


RESEARCH_SOURCE_EXTRACTION_CONTRACT_VERSION = "research-source-extraction-v1"


class RejectedResearchSourceDocument(BaseModel):
    source_type: str = "web"
    source_title: str = ""
    source_url: str = ""
    reason_codes: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ResearchSourceExtractionResult(BaseModel):
    result_mode: str = "research_source_extraction"
    contract_version: str = RESEARCH_SOURCE_EXTRACTION_CONTRACT_VERSION
    status: str = "ok"
    query: str = ""
    subquestion: str = ""
    source_records: list[ResearchSourceRecord] = Field(default_factory=list)
    observation_batch: ResearchObservationBatch
    rejected_documents: list[RejectedResearchSourceDocument] = Field(default_factory=list)
    document_count: int = 0
    extracted_count: int = 0
    metadata: dict[str, Any] = Field(default_factory=dict)


def extract_research_source_records(
    *,
    query: str = "",
    subquestion: str = "",
    documents: list[dict[str, Any]] | None = None,
    provider_source: str = "source_extraction",
    max_records_per_document: int = 1,
    metadata: dict[str, Any] | None = None,
) -> ResearchSourceExtractionResult:
    """Extract explicit source-sentence claims from approved source documents.

    This adapter does not search, fetch URLs, call providers, or write state. It
    only maps already-returned source/search text into app-owned source records
    when a claim can be copied from the source text.
    """

    normalized_query = normalize_text(query)
    normalized_subquestion = normalize_text(subquestion)
    normalized_provider = normalize_text(provider_source) or "source_extraction"
    source_documents = documents or []
    max_records = max(1, min(int(max_records_per_document or 1), 5))
    source_records: list[ResearchSourceRecord] = []
    rejected_documents: list[RejectedResearchSourceDocument] = []

    for index, item in enumerate(source_documents):
        document = _source_document(item)
        rejection_reasons = _document_rejection_reasons(document)
        if rejection_reasons:
            rejected_documents.append(
                _rejected_document(
                    document,
                    reason_codes=rejection_reasons,
                    provider_source=normalized_provider,
                )
            )
            continue

        explicit_record = _explicit_record(
            document,
            query=normalized_query,
            subquestion=normalized_subquestion,
            provider_source=normalized_provider,
            index=index,
        )
        if explicit_record is not None:
            source_records.append(explicit_record)
            continue

        candidates = _select_claim_sentences(
            content=document["content"],
            query=normalized_query,
            subquestion=normalized_subquestion,
            limit=max_records,
        )
        if not candidates:
            rejected_documents.append(
                _rejected_document(
                    document,
                    reason_codes=["no_relevant_claim_sentence"],
                    provider_source=normalized_provider,
                )
            )
            continue

        for sentence_index, sentence in candidates:
            source_records.append(
                ResearchSourceRecord(
                    source_type=document["source_type"],
                    source_title=document["source_title"],
                    source_url=document["source_url"],
                    claim=sentence,
                    excerpt=sentence,
                    quality=document["quality"],
                    relevance=document["relevance"],
                    metadata={
                        **document["metadata"],
                        "provider_source": normalized_provider,
                        "provider_raw": document["raw_payload"],
                        "source_extraction": {
                            "contract_version": (
                                RESEARCH_SOURCE_EXTRACTION_CONTRACT_VERSION
                            ),
                            "method": "source_sentence_overlap",
                            "query": normalized_query,
                            "subquestion": normalized_subquestion,
                            "document_index": index,
                            "sentence_index": sentence_index,
                            "claim_is_source_sentence": True,
                        },
                    },
                )
            )

    batch = build_research_observation_batch(
        query=normalized_query,
        subquestion=normalized_subquestion,
        sources=[record.model_dump(mode="json") for record in source_records],
        provider_source=normalized_provider,
        metadata={
            **(metadata or {}),
            "source_extraction": {
                "contract_version": RESEARCH_SOURCE_EXTRACTION_CONTRACT_VERSION,
            },
        },
    )
    return ResearchSourceExtractionResult(
        status=_status(source_records, rejected_documents),
        query=normalized_query,
        subquestion=normalized_subquestion,
        source_records=source_records,
        observation_batch=batch,
        rejected_documents=rejected_documents,
        document_count=len(source_documents),
        extracted_count=len(source_records),
        metadata={
            **(metadata or {}),
            "writes_research_state": False,
            "writes_evidence": False,
            "writes_long_term_memory": False,
            "writes_recommendation_events": False,
            "external_call": False,
            "provider_source": normalized_provider,
            "rejected_document_count": len(rejected_documents),
        },
    )


def _source_document(item: dict[str, Any]) -> dict[str, Any]:
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
    content = normalize_text(
        payload.get("content")
        or payload.get("raw_content")
        or payload.get("text")
        or payload.get("body")
        or payload.get("snippet")
        or payload.get("summary")
        or payload.get("excerpt")
    )
    return {
        "source_type": source_type,
        "source_title": source_title,
        "source_url": source_url,
        "content": content,
        "claim": normalize_text(payload.get("claim") or metadata.get("claim")),
        "excerpt": normalize_text(payload.get("excerpt") or metadata.get("excerpt")),
        "quality": _quality(payload.get("quality") or metadata.get("quality")),
        "relevance": _relevance(payload.get("relevance") or payload.get("score")),
        "metadata": metadata,
        "raw_payload": payload,
    }


def _document_rejection_reasons(document: dict[str, Any]) -> list[str]:
    reasons: list[str] = []
    if not document["source_title"] and not document["source_url"]:
        reasons.append("missing_source_metadata")
    if not document["content"] and not document["claim"]:
        reasons.append("missing_source_content")
    return reasons


def _explicit_record(
    document: dict[str, Any],
    *,
    query: str,
    subquestion: str,
    provider_source: str,
    index: int,
) -> ResearchSourceRecord | None:
    if not document["claim"]:
        return None
    excerpt = document["excerpt"] or document["claim"]
    return ResearchSourceRecord(
        source_type=document["source_type"],
        source_title=document["source_title"],
        source_url=document["source_url"],
        claim=document["claim"],
        excerpt=excerpt,
        quality=document["quality"],
        relevance=document["relevance"],
        metadata={
            **document["metadata"],
            "provider_source": provider_source,
            "provider_raw": document["raw_payload"],
            "source_extraction": {
                "contract_version": RESEARCH_SOURCE_EXTRACTION_CONTRACT_VERSION,
                "method": "provided_claim",
                "query": query,
                "subquestion": subquestion,
                "document_index": index,
                "claim_is_source_sentence": bool(document["content"])
                and document["claim"] in document["content"],
            },
        },
    )


def _select_claim_sentences(
    *,
    content: str,
    query: str,
    subquestion: str,
    limit: int,
) -> list[tuple[int, str]]:
    sentences = _split_sentences(content)
    terms = _query_terms(f"{query} {subquestion}")
    scored: list[tuple[int, int, str]] = []
    for index, sentence in enumerate(sentences):
        if len(sentence) < 20:
            continue
        score = _sentence_score(sentence, terms)
        if terms and score <= 0:
            continue
        scored.append((score, -index, sentence))
    scored.sort(reverse=True)
    selected: list[tuple[int, str]] = []
    for _score, negative_index, sentence in scored[:limit]:
        selected.append((-negative_index, sentence))
    selected.sort(key=lambda item: item[0])
    return selected


def _split_sentences(content: str) -> list[str]:
    chunks = re.split(r"(?<=[.!?。！？])\s+|\n+", content)
    return [normalize_text(chunk) for chunk in chunks if normalize_text(chunk)]


def _query_terms(text: str) -> set[str]:
    return {term for term in re.findall(r"[a-z0-9]{3,}", text.lower())}


def _sentence_score(sentence: str, terms: set[str]) -> int:
    lowered = sentence.lower()
    return sum(1 for term in terms if term in lowered)


def _rejected_document(
    document: dict[str, Any],
    *,
    reason_codes: list[str],
    provider_source: str,
) -> RejectedResearchSourceDocument:
    return RejectedResearchSourceDocument(
        source_type=document["source_type"],
        source_title=document["source_title"],
        source_url=document["source_url"],
        reason_codes=reason_codes,
        metadata={
            "provider_source": provider_source,
            "provider_raw": document["raw_payload"],
        },
    )


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


def _status(
    source_records: list[ResearchSourceRecord],
    rejected_documents: list[RejectedResearchSourceDocument],
) -> str:
    if source_records and rejected_documents:
        return "partial"
    if source_records:
        return "ok"
    return "empty_result"
