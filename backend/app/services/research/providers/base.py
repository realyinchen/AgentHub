from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any
from uuid import UUID

from app.services.research.contracts import (
    ResearchEvidence,
    ResearchRunListResult,
    ResearchStateResult,
)


class ResearchProvider(ABC):
    """Provider interface for app-owned research state."""

    provider_name: str

    @abstractmethod
    async def start_run(
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
        raise NotImplementedError

    @abstractmethod
    async def inspect_run(
        self,
        *,
        user_id: UUID,
        run_id: UUID,
        limit_steps: int = 20,
        limit_evidence: int = 20,
    ) -> ResearchStateResult:
        raise NotImplementedError

    @abstractmethod
    async def list_runs(
        self,
        *,
        user_id: UUID,
        status: str = "",
        limit: int = 50,
        offset: int = 0,
    ) -> ResearchRunListResult:
        raise NotImplementedError

    @abstractmethod
    async def log_search(
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
        raise NotImplementedError

    @abstractmethod
    async def log_visit(
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
        raise NotImplementedError

    @abstractmethod
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
        raise NotImplementedError

    @abstractmethod
    async def update_state(
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
        raise NotImplementedError

    @abstractmethod
    async def finish_run(
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
        raise NotImplementedError
