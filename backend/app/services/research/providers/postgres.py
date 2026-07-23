from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.base import utc_now
from app.models.research import (
    ResearchEvidenceRecord,
    ResearchRunRecord,
    ResearchStateSnapshotRecord,
    ResearchStepRecord,
)
from app.services.research.contracts import (
    ResearchEvidence,
    ResearchRun,
    ResearchRunListResult,
    ResearchStateResult,
    ResearchStateSnapshot,
    ResearchStep,
    clean_string_list,
    validate_research_token,
    RESEARCH_RUN_STATUSES,
)
from app.services.research.evidence_admission import (
    admit_research_evidence,
    attach_evidence_admission_metadata,
)
from app.services.research.providers.base import ResearchProvider


class PostgresResearchProvider(ResearchProvider):
    """Postgres implementation of the app-owned research contract."""

    provider_name = "postgres"

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

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
        run_contract = ResearchRun(
            user_id=user_id,
            thread_id=thread_id,
            objective=objective,
            mode=mode,
            budget=budget or {},
            stop_criteria=stop_criteria or [],
            metadata=metadata or {},
        )
        run = ResearchRunRecord(
            user_id=run_contract.user_id,
            thread_id=run_contract.thread_id,
            objective=run_contract.objective,
            status=run_contract.status,
            mode=run_contract.mode,
            budget=run_contract.budget,
            stop_criteria=run_contract.stop_criteria,
            metadata_json=run_contract.metadata,
        )
        self.session.add(run)
        await self.session.flush()
        await self.session.refresh(run)

        step = await self._add_step(
            run_id=run.id,
            step_type="plan",
            status="completed",
            title="Start research",
            rationale="Initialize structured research state.",
            input_json={
                "objective": run.objective,
                "subquestions": subquestions or [],
                "gaps": gaps or [],
                "next_actions": next_actions or [],
            },
        )
        await self._add_snapshot(
            run=run,
            step_id=step.id,
            subquestions=subquestions or [],
            gaps=gaps or [],
            next_actions=next_actions or [],
            metadata={"event": "start_research"},
        )
        await self.session.flush()
        return await self.inspect_run(user_id=user_id, run_id=run.id)

    async def inspect_run(
        self,
        *,
        user_id: UUID,
        run_id: UUID,
        limit_steps: int = 20,
        limit_evidence: int = 20,
    ) -> ResearchStateResult:
        run = await self._get_run(user_id=user_id, run_id=run_id)
        state = await self._latest_state(run)
        steps = await self._list_steps(run_id, limit_steps)
        evidence = await self._list_evidence(run_id, limit_evidence)
        return ResearchStateResult(
            run=self._run_from_record(run),
            state=self._state_from_record(state),
            steps=[self._step_from_record(step) for step in steps],
            evidence=[self._evidence_from_record(item) for item in evidence],
            provider_sources=[self.provider_name],
        )

    async def list_runs(
        self,
        *,
        user_id: UUID,
        status: str = "",
        limit: int = 50,
        offset: int = 0,
    ) -> ResearchRunListResult:
        stmt = select(ResearchRunRecord).where(ResearchRunRecord.user_id == user_id)
        if status.strip():
            stmt = stmt.where(
                ResearchRunRecord.status
                == validate_research_token("status", status, RESEARCH_RUN_STATUSES)
            )
        count_stmt = select(func.count()).select_from(stmt.order_by(None).subquery())
        total = int(await self.session.scalar(count_stmt) or 0)
        page_limit = max(1, min(limit, 100))
        page_offset = max(0, offset)
        result = await self.session.execute(
            stmt.order_by(ResearchRunRecord.updated_at.desc())
            .offset(page_offset)
            .limit(page_limit)
        )
        return ResearchRunListResult(
            user_id=user_id,
            runs=[self._run_from_record(run) for run in result.scalars().all()],
            total=total,
            limit=page_limit,
            offset=page_offset,
            provider_sources=[self.provider_name],
        )

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
        run = await self._get_active_run(user_id=user_id, run_id=run_id)
        step = await self._add_step(
            run_id=run.id,
            step_type="search",
            status=status,
            title=f"Search: {query}",
            query=query,
            rationale=rationale,
            input_json={"query": query},
            output_json={"results": results or [], "result_count": len(results or [])},
            error=error,
            duration_ms=duration_ms,
        )
        await self._add_snapshot_from_previous(
            run=run,
            step_id=step.id,
            exhausted_queries=[query],
            next_actions=next_actions or [],
            metadata={"event": "search_research", "search_status": status},
        )
        await self._touch_run(run)
        return await self.inspect_run(user_id=user_id, run_id=run.id)

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
        run = await self._get_active_run(user_id=user_id, run_id=run_id)
        step = await self._add_step(
            run_id=run.id,
            step_type="visit",
            status=status,
            title=title or f"Visit: {url}",
            url=url,
            rationale=rationale,
            input_json={"url": url},
            output_json={"summary": summary},
            error=error,
            duration_ms=duration_ms,
        )
        await self._add_snapshot_from_previous(
            run=run,
            step_id=step.id,
            metadata={"event": "visit_source", "visit_status": status},
        )
        await self._touch_run(run)
        return await self.inspect_run(user_id=user_id, run_id=run.id)

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
        run = await self._get_active_run(user_id=user_id, run_id=run_id)
        admission = admit_research_evidence(
            ResearchEvidence.model_validate(evidence.model_copy(update={"run_id": run.id}))
        )
        admission_payload = admission.model_dump(mode="json")
        if not admission.allowed:
            step = await self._add_step(
                run_id=run.id,
                step_type="add_evidence",
                status="skipped",
                title="Reject evidence",
                input_json=evidence.model_dump(mode="json"),
                output_json={"evidence_admission": admission_payload},
                error=", ".join(admission.reason_codes),
            )
            await self._add_snapshot_from_previous(
                run=run,
                step_id=step.id,
                next_actions=next_actions or ["Collect source-backed evidence."],
                metadata={
                    "event": "add_evidence_rejected",
                    "evidence_admission": admission_payload,
                },
            )
            await self._touch_run(run)
            return await self.inspect_run(user_id=user_id, run_id=run.id)

        step = await self._add_step(
            run_id=run.id,
            step_type="add_evidence",
            status="completed",
            title="Add evidence",
            input_json=admission.evidence.model_dump(mode="json"),
        )
        normalized = ResearchEvidence.model_validate(
            attach_evidence_admission_metadata(
                admission.evidence,
                admission,
            ).model_copy(update={"run_id": run.id, "step_id": step.id})
        )
        record = ResearchEvidenceRecord(
            run_id=run.id,
            step_id=step.id,
            source_type=normalized.source_type,
            source_title=normalized.source_title,
            source_url=normalized.source_url,
            claim=normalized.claim,
            excerpt=normalized.excerpt,
            quality=normalized.quality,
            relevance=normalized.relevance,
            metadata_json=normalized.metadata,
        )
        self.session.add(record)
        await self.session.flush()
        await self.session.refresh(record)
        step.output_json = {
            "evidence_id": str(record.id),
            "evidence_admission": admission_payload,
        }

        await self._add_snapshot_from_previous(
            run=run,
            step_id=step.id,
            known_facts=known_facts or [record.claim],
            gaps=gaps or [],
            conflicts=conflicts or [],
            next_actions=next_actions or [],
            evidence_ids=[record.id],
            metadata={
                "event": "add_evidence",
                "evidence_admission": admission_payload,
            },
        )
        await self._touch_run(run)
        return await self.inspect_run(user_id=user_id, run_id=run.id)

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
        run = await self._get_active_run(user_id=user_id, run_id=run_id)
        step = await self._add_step(
            run_id=run.id,
            step_type="update_state",
            status="completed",
            title="Update research state",
            input_json={
                "subquestions": subquestions,
                "known_facts": known_facts,
                "gaps": gaps,
                "conflicts": conflicts,
                "exhausted_queries": exhausted_queries,
                "next_actions": next_actions,
                "budget": budget,
                "stop_criteria": stop_criteria,
                "replace": replace,
            },
        )
        await self._add_snapshot_from_previous(
            run=run,
            step_id=step.id,
            subquestions=subquestions,
            known_facts=known_facts,
            gaps=gaps,
            conflicts=conflicts,
            exhausted_queries=exhausted_queries,
            next_actions=next_actions,
            budget=budget,
            stop_criteria=stop_criteria,
            metadata={"event": "update_research_state", **(metadata or {})},
            replace=replace,
        )
        if budget is not None:
            run.budget = budget
        if stop_criteria is not None:
            run.stop_criteria = clean_string_list(stop_criteria)
        await self._touch_run(run)
        return await self.inspect_run(user_id=user_id, run_id=run.id)

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
        run = await self._get_active_run(user_id=user_id, run_id=run_id)
        final_status = validate_research_token("status", status, RESEARCH_RUN_STATUSES)
        if final_status == "active":
            final_status = "completed"
        step = await self._add_step(
            run_id=run.id,
            step_type="finish",
            status="completed" if final_status == "completed" else "failed",
            title="Finish research",
            input_json={"requested_status": status},
            output_json={"conclusion": conclusion},
        )
        run.status = final_status
        run.finished_at = utc_now()
        run.metadata_json = {**(run.metadata_json or {}), **(metadata or {})}
        previous = await self._latest_state(run)
        await self._add_snapshot(
            run=run,
            step_id=step.id,
            status=final_status,
            subquestions=previous.subquestions,
            known_facts=self._merge_list(previous.known_facts, known_facts, False),
            gaps=self._merge_list(previous.gaps, gaps, False),
            conflicts=self._merge_list(previous.conflicts, conflicts, False),
            exhausted_queries=previous.exhausted_queries,
            next_actions=[],
            evidence_ids=self._merge_ids(previous.evidence_ids, None, False),
            budget=previous.budget,
            stop_criteria=previous.stop_criteria,
            metadata={
                **(previous.metadata_json or {}),
                "event": "finish_research",
                "conclusion": conclusion,
                **(metadata or {}),
            },
        )
        await self._touch_run(run)
        return await self.inspect_run(user_id=user_id, run_id=run.id)

    async def _get_run(self, *, user_id: UUID, run_id: UUID) -> ResearchRunRecord:
        result = await self.session.execute(
            select(ResearchRunRecord).where(
                ResearchRunRecord.id == run_id,
                ResearchRunRecord.user_id == user_id,
            )
        )
        run = result.scalar_one_or_none()
        if run is None:
            raise ValueError("research run not found")
        return run

    async def _get_active_run(self, *, user_id: UUID, run_id: UUID) -> ResearchRunRecord:
        run = await self._get_run(user_id=user_id, run_id=run_id)
        if run.status != "active":
            raise ValueError("research run is not active")
        return run

    async def _add_step(
        self,
        *,
        run_id: UUID,
        step_type: str,
        status: str,
        title: str = "",
        query: str = "",
        url: str = "",
        rationale: str = "",
        input_json: dict[str, Any] | None = None,
        output_json: dict[str, Any] | None = None,
        error: str | None = None,
        duration_ms: int = 0,
    ) -> ResearchStepRecord:
        contract = ResearchStep(
            run_id=run_id,
            step_type=step_type,
            status=status,
            title=title,
            query=query,
            url=url,
            rationale=rationale,
            input=input_json or {},
            output=output_json or {},
            error=error,
            duration_ms=duration_ms,
        )
        record = ResearchStepRecord(
            run_id=contract.run_id,
            step_type=contract.step_type,
            status=contract.status,
            title=contract.title,
            query=contract.query,
            url=contract.url,
            rationale=contract.rationale,
            input_json=contract.input,
            output_json=contract.output,
            error=contract.error,
            duration_ms=contract.duration_ms,
        )
        self.session.add(record)
        await self.session.flush()
        await self.session.refresh(record)
        return record

    async def _add_snapshot(
        self,
        *,
        run: ResearchRunRecord,
        step_id: UUID | None = None,
        status: str | None = None,
        subquestions: list[str] | None = None,
        known_facts: list[str] | None = None,
        gaps: list[str] | None = None,
        conflicts: list[str] | None = None,
        exhausted_queries: list[str] | None = None,
        next_actions: list[str] | None = None,
        evidence_ids: list[UUID] | None = None,
        budget: dict[str, Any] | None = None,
        stop_criteria: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> ResearchStateSnapshotRecord:
        contract = ResearchStateSnapshot(
            run_id=run.id,
            step_id=step_id,
            objective=run.objective,
            status=status or run.status,
            subquestions=subquestions or [],
            known_facts=known_facts or [],
            gaps=gaps or [],
            conflicts=conflicts or [],
            exhausted_queries=exhausted_queries or [],
            next_actions=next_actions or [],
            evidence_ids=evidence_ids or [],
            budget=budget or run.budget or {},
            stop_criteria=stop_criteria or run.stop_criteria or [],
            metadata=metadata or {},
        )
        record = ResearchStateSnapshotRecord(
            run_id=contract.run_id,
            step_id=contract.step_id,
            objective=contract.objective,
            status=contract.status,
            subquestions=contract.subquestions,
            known_facts=contract.known_facts,
            gaps=contract.gaps,
            conflicts=contract.conflicts,
            exhausted_queries=contract.exhausted_queries,
            next_actions=contract.next_actions,
            evidence_ids=[str(item) for item in contract.evidence_ids],
            budget=contract.budget,
            stop_criteria=contract.stop_criteria,
            metadata_json=contract.metadata,
        )
        self.session.add(record)
        await self.session.flush()
        await self.session.refresh(record)
        return record

    async def _add_snapshot_from_previous(
        self,
        *,
        run: ResearchRunRecord,
        step_id: UUID | None,
        status: str | None = None,
        subquestions: list[str] | None = None,
        known_facts: list[str] | None = None,
        gaps: list[str] | None = None,
        conflicts: list[str] | None = None,
        exhausted_queries: list[str] | None = None,
        next_actions: list[str] | None = None,
        evidence_ids: list[UUID] | None = None,
        budget: dict[str, Any] | None = None,
        stop_criteria: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        replace: bool = False,
    ) -> ResearchStateSnapshotRecord:
        previous = await self._latest_state(run)
        return await self._add_snapshot(
            run=run,
            step_id=step_id,
            status=status or run.status,
            subquestions=self._merge_list(previous.subquestions, subquestions, replace),
            known_facts=self._merge_list(previous.known_facts, known_facts, replace),
            gaps=self._merge_list(previous.gaps, gaps, replace),
            conflicts=self._merge_list(previous.conflicts, conflicts, replace),
            exhausted_queries=self._merge_list(
                previous.exhausted_queries,
                exhausted_queries,
                replace,
            ),
            next_actions=self._merge_list(previous.next_actions, next_actions, replace),
            evidence_ids=self._merge_ids(previous.evidence_ids, evidence_ids, replace),
            budget=budget if budget is not None else previous.budget,
            stop_criteria=(
                clean_string_list(stop_criteria)
                if stop_criteria is not None
                else previous.stop_criteria
            ),
            metadata={**(previous.metadata_json or {}), **(metadata or {})},
        )

    async def _latest_state(
        self,
        run: ResearchRunRecord,
    ) -> ResearchStateSnapshotRecord:
        result = await self.session.execute(
            select(ResearchStateSnapshotRecord)
            .where(ResearchStateSnapshotRecord.run_id == run.id)
            .order_by(ResearchStateSnapshotRecord.created_at.desc())
            .limit(1)
        )
        state = result.scalar_one_or_none()
        if state is not None:
            return state
        return await self._add_snapshot(run=run, metadata={"event": "implicit_state"})

    async def _list_steps(self, run_id: UUID, limit: int) -> list[ResearchStepRecord]:
        result = await self.session.execute(
            select(ResearchStepRecord)
            .where(ResearchStepRecord.run_id == run_id)
            .order_by(ResearchStepRecord.created_at.asc())
            .limit(max(1, min(limit, 100)))
        )
        return list(result.scalars().all())

    async def _list_evidence(
        self,
        run_id: UUID,
        limit: int,
    ) -> list[ResearchEvidenceRecord]:
        result = await self.session.execute(
            select(ResearchEvidenceRecord)
            .where(ResearchEvidenceRecord.run_id == run_id)
            .order_by(ResearchEvidenceRecord.created_at.desc())
            .limit(max(1, min(limit, 100)))
        )
        return list(result.scalars().all())

    async def _touch_run(self, run: ResearchRunRecord) -> None:
        run.updated_at = utc_now()
        await self.session.flush()

    def _merge_list(
        self,
        current: list[str] | None,
        incoming: list[str] | None,
        replace: bool,
    ) -> list[str]:
        if incoming is None:
            return clean_string_list(current)
        if replace:
            return clean_string_list(incoming)
        return clean_string_list([*(current or []), *incoming])

    def _merge_ids(
        self,
        current: list[Any] | None,
        incoming: list[UUID] | None,
        replace: bool,
    ) -> list[UUID]:
        if incoming is None:
            raw_ids = current or []
        elif replace:
            raw_ids = incoming
        else:
            raw_ids = [*(current or []), *incoming]
        seen: set[str] = set()
        merged: list[UUID] = []
        for item in raw_ids:
            value = UUID(str(item))
            key = str(value)
            if key not in seen:
                seen.add(key)
                merged.append(value)
        return merged

    def _run_from_record(self, record: ResearchRunRecord) -> ResearchRun:
        return ResearchRun(
            id=record.id,
            user_id=record.user_id,
            thread_id=record.thread_id,
            objective=record.objective,
            status=record.status,
            mode=record.mode,
            budget=record.budget or {},
            stop_criteria=record.stop_criteria or [],
            metadata=record.metadata_json or {},
            started_at=record.started_at,
            finished_at=record.finished_at,
            created_at=record.created_at,
            updated_at=record.updated_at,
        )

    def _step_from_record(self, record: ResearchStepRecord) -> ResearchStep:
        return ResearchStep(
            id=record.id,
            run_id=record.run_id,
            step_type=record.step_type,
            status=record.status,
            title=record.title,
            query=record.query,
            url=record.url,
            rationale=record.rationale,
            input=record.input_json or {},
            output=record.output_json or {},
            error=record.error,
            duration_ms=record.duration_ms,
            created_at=record.created_at,
            updated_at=record.updated_at,
        )

    def _evidence_from_record(self, record: ResearchEvidenceRecord) -> ResearchEvidence:
        return ResearchEvidence(
            id=record.id,
            run_id=record.run_id,
            step_id=record.step_id,
            source_type=record.source_type,
            source_title=record.source_title,
            source_url=record.source_url,
            claim=record.claim,
            excerpt=record.excerpt,
            quality=record.quality,
            relevance=record.relevance,
            metadata=record.metadata_json or {},
            created_at=record.created_at,
            updated_at=record.updated_at,
        )

    def _state_from_record(
        self,
        record: ResearchStateSnapshotRecord,
    ) -> ResearchStateSnapshot:
        return ResearchStateSnapshot(
            id=record.id,
            run_id=record.run_id,
            step_id=record.step_id,
            objective=record.objective,
            status=record.status,
            subquestions=record.subquestions or [],
            known_facts=record.known_facts or [],
            gaps=record.gaps or [],
            conflicts=record.conflicts or [],
            exhausted_queries=record.exhausted_queries or [],
            next_actions=record.next_actions or [],
            evidence_ids=[UUID(str(item)) for item in record.evidence_ids or []],
            budget=record.budget or {},
            stop_criteria=record.stop_criteria or [],
            metadata=record.metadata_json or {},
            created_at=record.created_at,
        )
