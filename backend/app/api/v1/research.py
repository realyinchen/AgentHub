"""Deep Search / Deep Research state endpoints."""

from uuid import UUID

from fastapi import APIRouter, Query

from app.schemas.research import (
    ResearchEvidenceRequest,
    ResearchFinishRequest,
    ResearchRunListResult,
    ResearchSearchRequest,
    ResearchStartRequest,
    ResearchStateResult,
    ResearchStateUpdateRequest,
    ResearchVisitRequest,
)
from app.services.research import ResearchEvidence, get_research_orchestrator

api_router = APIRouter(prefix="/research", tags=["Research"])


@api_router.get("/runs", response_model=ResearchRunListResult)
async def list_research_runs(
    user_id: UUID = Query(...),
    status: str = Query(default=""),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> ResearchRunListResult:
    return await get_research_orchestrator().list_research_runs(
        user_id=user_id,
        status=status,
        limit=limit,
        offset=offset,
    )


@api_router.get("/{run_id}", response_model=ResearchStateResult)
async def inspect_research_state(
    run_id: UUID,
    user_id: UUID = Query(...),
    limit_steps: int = Query(default=20, ge=1, le=100),
    limit_evidence: int = Query(default=20, ge=1, le=100),
) -> ResearchStateResult:
    return await get_research_orchestrator().inspect_research_state(
        user_id=user_id,
        run_id=run_id,
        limit_steps=limit_steps,
        limit_evidence=limit_evidence,
    )


@api_router.post("/start", response_model=ResearchStateResult)
async def start_research(request: ResearchStartRequest) -> ResearchStateResult:
    return await get_research_orchestrator().start_research(
        user_id=request.user_id,
        objective=request.objective,
        thread_id=request.thread_id,
        mode=request.mode,
        subquestions=request.subquestions,
        gaps=request.gaps,
        next_actions=request.next_actions,
        budget=request.budget,
        stop_criteria=request.stop_criteria,
        metadata=request.metadata,
    )


@api_router.post("/search", response_model=ResearchStateResult)
async def search_research(request: ResearchSearchRequest) -> ResearchStateResult:
    return await get_research_orchestrator().search_research(
        user_id=request.user_id,
        run_id=request.run_id,
        query=request.query,
        status=request.status,
        rationale=request.rationale,
        results=request.results,
        next_actions=request.next_actions,
        duration_ms=request.duration_ms,
        error=request.error,
    )


@api_router.post("/visit", response_model=ResearchStateResult)
async def visit_source(request: ResearchVisitRequest) -> ResearchStateResult:
    return await get_research_orchestrator().visit_source(
        user_id=request.user_id,
        run_id=request.run_id,
        url=request.url,
        title=request.title,
        status=request.status,
        summary=request.summary,
        rationale=request.rationale,
        duration_ms=request.duration_ms,
        error=request.error,
    )


@api_router.post("/evidence", response_model=ResearchStateResult)
async def add_evidence(request: ResearchEvidenceRequest) -> ResearchStateResult:
    evidence = ResearchEvidence(
        run_id=request.run_id,
        source_type=request.source_type,
        source_title=request.source_title,
        source_url=request.source_url,
        claim=request.claim,
        excerpt=request.excerpt,
        quality=request.quality,
        relevance=request.relevance,
        metadata=request.metadata,
    )
    return await get_research_orchestrator().add_evidence(
        user_id=request.user_id,
        run_id=request.run_id,
        evidence=evidence,
        known_facts=request.known_facts,
        gaps=request.gaps,
        conflicts=request.conflicts,
        next_actions=request.next_actions,
    )


@api_router.post("/state", response_model=ResearchStateResult)
async def update_research_state(
    request: ResearchStateUpdateRequest,
) -> ResearchStateResult:
    return await get_research_orchestrator().update_research_state(
        user_id=request.user_id,
        run_id=request.run_id,
        subquestions=request.subquestions,
        known_facts=request.known_facts,
        gaps=request.gaps,
        conflicts=request.conflicts,
        exhausted_queries=request.exhausted_queries,
        next_actions=request.next_actions,
        budget=request.budget,
        stop_criteria=request.stop_criteria,
        metadata=request.metadata,
        replace=request.replace,
    )


@api_router.post("/finish", response_model=ResearchStateResult)
async def finish_research(request: ResearchFinishRequest) -> ResearchStateResult:
    return await get_research_orchestrator().finish_research(
        user_id=request.user_id,
        run_id=request.run_id,
        conclusion=request.conclusion,
        status=request.status,
        known_facts=request.known_facts,
        gaps=request.gaps,
        conflicts=request.conflicts,
        metadata=request.metadata,
    )
