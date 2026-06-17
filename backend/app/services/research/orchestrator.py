from __future__ import annotations

from typing import Any
from uuid import UUID

from app.infra.database import get_database
from app.services.research.contracts import (
    ResearchEvidence,
    ResearchRunListResult,
    ResearchStateResult,
)
from app.services.research.providers.postgres import PostgresResearchProvider


class ResearchOrchestrator:
    """Coordinates Deep Search state providers behind the app-owned contract."""

    async def start_research(
        self,
        *,
        user_id: UUID,
        objective: str,
        thread_id: UUID | None = None,
        mode: str = "deep_search",
        subquestions: list[str] | None = None,
        gaps: list[str] | None = None,
        next_actions: list[str] | None = None,
        budget: dict[str, Any] | None = None,
        stop_criteria: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> ResearchStateResult:
        db = get_database()
        async with db.session() as session:
            provider = PostgresResearchProvider(session)
            return await provider.start_run(
                user_id=user_id,
                objective=objective,
                thread_id=thread_id,
                mode=mode,
                subquestions=subquestions,
                gaps=gaps,
                next_actions=next_actions,
                budget=budget,
                stop_criteria=stop_criteria,
                metadata=metadata,
            )

    async def inspect_research_state(
        self,
        *,
        user_id: UUID,
        run_id: UUID,
        limit_steps: int = 20,
        limit_evidence: int = 20,
    ) -> ResearchStateResult:
        db = get_database()
        async with db.session() as session:
            provider = PostgresResearchProvider(session)
            return await provider.inspect_run(
                user_id=user_id,
                run_id=run_id,
                limit_steps=limit_steps,
                limit_evidence=limit_evidence,
            )

    async def list_research_runs(
        self,
        *,
        user_id: UUID,
        status: str = "",
        limit: int = 50,
        offset: int = 0,
    ) -> ResearchRunListResult:
        db = get_database()
        async with db.session() as session:
            provider = PostgresResearchProvider(session)
            return await provider.list_runs(
                user_id=user_id,
                status=status,
                limit=limit,
                offset=offset,
            )

    async def search_research(
        self,
        *,
        user_id: UUID,
        run_id: UUID,
        query: str,
        status: str = "completed",
        rationale: str = "",
        results: list[dict[str, Any]] | None = None,
        next_actions: list[str] | None = None,
        duration_ms: int = 0,
        error: str | None = None,
    ) -> ResearchStateResult:
        db = get_database()
        async with db.session() as session:
            provider = PostgresResearchProvider(session)
            return await provider.log_search(
                user_id=user_id,
                run_id=run_id,
                query=query,
                status=status,
                rationale=rationale,
                results=results,
                next_actions=next_actions,
                duration_ms=duration_ms,
                error=error,
            )

    async def visit_source(
        self,
        *,
        user_id: UUID,
        run_id: UUID,
        url: str,
        title: str = "",
        status: str = "completed",
        summary: str = "",
        rationale: str = "",
        duration_ms: int = 0,
        error: str | None = None,
    ) -> ResearchStateResult:
        db = get_database()
        async with db.session() as session:
            provider = PostgresResearchProvider(session)
            return await provider.log_visit(
                user_id=user_id,
                run_id=run_id,
                url=url,
                title=title,
                status=status,
                summary=summary,
                rationale=rationale,
                duration_ms=duration_ms,
                error=error,
            )

    async def add_evidence(
        self,
        *,
        user_id: UUID,
        run_id: UUID,
        evidence: ResearchEvidence,
        known_facts: list[str] | None = None,
        gaps: list[str] | None = None,
        conflicts: list[str] | None = None,
        next_actions: list[str] | None = None,
    ) -> ResearchStateResult:
        db = get_database()
        async with db.session() as session:
            provider = PostgresResearchProvider(session)
            return await provider.add_evidence(
                user_id=user_id,
                run_id=run_id,
                evidence=evidence,
                known_facts=known_facts,
                gaps=gaps,
                conflicts=conflicts,
                next_actions=next_actions,
            )

    async def update_research_state(
        self,
        *,
        user_id: UUID,
        run_id: UUID,
        subquestions: list[str] | None = None,
        known_facts: list[str] | None = None,
        gaps: list[str] | None = None,
        conflicts: list[str] | None = None,
        exhausted_queries: list[str] | None = None,
        next_actions: list[str] | None = None,
        budget: dict[str, Any] | None = None,
        stop_criteria: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        replace: bool = False,
    ) -> ResearchStateResult:
        db = get_database()
        async with db.session() as session:
            provider = PostgresResearchProvider(session)
            return await provider.update_state(
                user_id=user_id,
                run_id=run_id,
                subquestions=subquestions,
                known_facts=known_facts,
                gaps=gaps,
                conflicts=conflicts,
                exhausted_queries=exhausted_queries,
                next_actions=next_actions,
                budget=budget,
                stop_criteria=stop_criteria,
                metadata=metadata,
                replace=replace,
            )

    async def finish_research(
        self,
        *,
        user_id: UUID,
        run_id: UUID,
        conclusion: str,
        status: str = "completed",
        known_facts: list[str] | None = None,
        gaps: list[str] | None = None,
        conflicts: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> ResearchStateResult:
        db = get_database()
        async with db.session() as session:
            provider = PostgresResearchProvider(session)
            return await provider.finish_run(
                user_id=user_id,
                run_id=run_id,
                conclusion=conclusion,
                status=status,
                known_facts=known_facts,
                gaps=gaps,
                conflicts=conflicts,
                metadata=metadata,
            )


_research_orchestrator: ResearchOrchestrator | None = None


def get_research_orchestrator() -> ResearchOrchestrator:
    global _research_orchestrator
    if _research_orchestrator is None:
        _research_orchestrator = ResearchOrchestrator()
    return _research_orchestrator
