from __future__ import annotations

from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field

from app.services.research.contracts import ResearchStateResult, normalize_text
from app.services.research.orchestrator import get_research_orchestrator
from app.services.research.source_acquisition import (
    ResearchObservationBatch,
    build_research_observation_batch,
)


RESEARCH_SOURCE_COLLECTION_CONTRACT_VERSION = "research-source-collection-v1"


class ResearchSourceCollectionResult(BaseModel):
    result_mode: str = "research_source_collection"
    contract_version: str = RESEARCH_SOURCE_COLLECTION_CONTRACT_VERSION
    user_id: UUID
    run_id: UUID
    query: str
    status: str
    observation_batch: ResearchObservationBatch
    research_state: ResearchStateResult
    metadata: dict[str, Any] = Field(default_factory=dict)


async def collect_research_sources(
    *,
    user_id: UUID,
    run_id: UUID,
    query: str,
    sources: list[dict[str, Any]] | None = None,
    subquestion: str = "",
    provider_source: str = "source_collection",
    status: str = "completed",
    rationale: str = "",
    next_actions: list[str] | None = None,
    duration_ms: int = 0,
    error: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> ResearchSourceCollectionResult:
    """Normalize source records and log search/visit state for a run.

    This adapter does not perform a live external call and does not store
    evidence. It records the search/visit trace in research state, then returns
    app-owned observations that can later be passed to add_evidence or the
    local harness.
    """

    batch = build_research_observation_batch(
        query=query,
        subquestion=subquestion,
        sources=sources or [],
        provider_source=provider_source,
        metadata={
            **(metadata or {}),
            "source_collection": {
                "contract_version": RESEARCH_SOURCE_COLLECTION_CONTRACT_VERSION,
                "run_id": str(run_id),
            },
        },
    )
    search_status = _search_status(status, batch)
    research = get_research_orchestrator()
    research_state = await research.search_research(
        user_id=user_id,
        run_id=run_id,
        query=query,
        status=search_status,
        rationale=normalize_text(rationale)
        or f"Collect source records for: {query}",
        results=_search_results(batch),
        next_actions=next_actions
        or _default_next_actions(batch.observation_count),
        duration_ms=duration_ms,
        error=error,
    )
    for observation in batch.observations:
        if not observation.source_url:
            continue
        research_state = await research.visit_source(
            user_id=user_id,
            run_id=run_id,
            url=observation.source_url,
            title=observation.source_title,
            summary=observation.excerpt,
            rationale=(
                "Record accepted normalized source before evidence admission."
            ),
        )

    return ResearchSourceCollectionResult(
        user_id=user_id,
        run_id=run_id,
        query=normalize_text(query),
        status=search_status,
        observation_batch=batch,
        research_state=research_state,
        metadata={
            "writes_research_state": True,
            "writes_long_term_memory": False,
            "writes_recommendation_events": False,
            "writes_evidence": False,
            "external_call": False,
            "provider_source": provider_source,
            "source_count": batch.source_count,
            "observation_count": batch.observation_count,
            "rejected_source_count": len(batch.rejected_sources),
        },
    )


def _search_status(status: str, batch: ResearchObservationBatch) -> str:
    token = normalize_text(status).lower().replace(" ", "_")
    if token in {"timeout", "failed", "skipped"}:
        return token
    if batch.observation_count <= 0:
        return "empty_result"
    return "completed"


def _default_next_actions(observation_count: int) -> list[str]:
    if observation_count > 0:
        return ["Admit accepted observations as evidence or run the local harness."]
    return ["Collect stronger source records with claim, excerpt, and source metadata."]


def _search_results(batch: ResearchObservationBatch) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for observation in batch.observations:
        results.append(
            {
                "title": observation.source_title,
                "url": observation.source_url,
                "claim": observation.claim,
                "excerpt": observation.excerpt,
                "quality": observation.quality,
                "relevance": observation.relevance,
                "accepted": True,
            }
        )
    for rejected in batch.rejected_sources:
        results.append(
            {
                "title": rejected.source_title,
                "url": rejected.source_url,
                "reason_codes": rejected.reason_codes,
                "accepted": False,
            }
        )
    return results
