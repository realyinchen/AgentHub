from __future__ import annotations

import json
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.chat import UserInput
from app.services.agent_core.certification_contracts import AgentModeAdmission
from app.services.agent_core.context_coordinator import (
    ContextPreparationError,
    ControllerContextCoordinator,
)
from app.services.agent_core.prompt_contracts import (
    ControllerModelRequest,
    TrustedMemoryContext,
    TrustedTaskContext,
    TrustedWorkingStateContext,
)
from app.services.agent_core.working_state import (
    WorkingStateRecoveryService,
)
from app.services.conversation.summary_llm_provider import (
    LLMSummaryProvider,
)
from app.services.memory.version_store import MemoryVersionStore
from app.services.tasks.repository import TaskRepository


class ControllerRequestBuilder:
    """Build one complete, source-partitioned Controller request."""

    def __init__(
        self,
        *,
        context_coordinator: ControllerContextCoordinator | None = None,
        working_state: WorkingStateRecoveryService | None = None,
        tasks: TaskRepository | None = None,
    ) -> None:
        self._contexts = (
            context_coordinator or ControllerContextCoordinator()
        )
        self._working_state = (
            working_state or WorkingStateRecoveryService()
        )
        self._tasks = tasks or TaskRepository()

    async def build(
        self,
        db: AsyncSession,
        *,
        user_input: UserInput,
        model_name: str,
        admission: AgentModeAdmission,
        journal_sequence_watermark: int | None = None,
    ) -> ControllerModelRequest:
        memories = await self._memory_context(
            db,
            user_id=user_input.user_id,
        )
        task = await self._task_context(
            db,
            user_id=user_input.user_id,
            thread_id=user_input.thread_id,
        )
        working = await self._working_state.rebuild(
            db,
            user_id=user_input.user_id,
            thread_id=user_input.thread_id,
            active_goal=task.goal if task is not None else None,
        )
        working_context = TrustedWorkingStateContext(
            last_turn_status=working.last_turn_status,
            active_goal=working.active_goal,
            pending_question=(
                working.pending_clarification.question
                if working.pending_clarification is not None
                else None
            ),
        )
        summary_provider = LLMSummaryProvider(
            model_name=model_name,
            admission=admission,
        )
        assembled = await self._contexts.prepare(
            db,
            user_id=user_input.user_id,
            thread_id=user_input.thread_id,
            current_request_id=user_input.request_id,
            current_user_message=user_input.content,
            summary_provider=summary_provider,
            memories=memories,
            working_state=working_context,
            task=task,
            through_sequence=journal_sequence_watermark,
        )
        return ControllerModelRequest(
            model_name=model_name,
            current_user_message=user_input.content,
            context=assembled.snapshot,
            admission=admission,
        )

    async def _memory_context(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
    ) -> list[TrustedMemoryContext]:
        records = await MemoryVersionStore(db).list_current(
            user_id=user_id,
            limit=50,
        )
        return [
            TrustedMemoryContext(
                schema_key=record.schema_key,
                fact=_memory_fact(record),
            )
            for record in records
        ]

    async def _task_context(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        thread_id: UUID,
    ) -> TrustedTaskContext | None:
        active = await self._tasks.active_for_thread(
            db,
            user_id=user_id,
            thread_id=thread_id,
            for_update=False,
        )
        if len(active) > 1:
            raise ContextPreparationError(
                "multiple active tasks require reconciliation"
            )
        if not active:
            return None
        state = active[0]
        if state.current_plan_version_id is None:
            raise ContextPreparationError(
                "active task has no current plan version"
            )
        plan = await self._tasks.get_plan_version(
            db,
            state.current_plan_version_id,
        )
        next_step = None
        if state.status == "waiting" and state.pending_clarification is not None:
            next_step = state.pending_clarification.question
        elif plan.draft.steps:
            next_step = plan.draft.steps[0].title
        status = {
            "pending": "planning",
            "running": "running",
            "waiting": "waiting_clarification",
            "failed": "failed",
        }[state.status]
        return TrustedTaskContext(
            status=status,
            goal=plan.draft.goal,
            next_step=next_step,
        )


def _memory_fact(record) -> str:
    quote = str(record.evidence_quote or "").strip()
    if quote:
        return quote
    return (
        f"{record.subject} {record.predicate} "
        + json.dumps(
            record.value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    )


__all__ = ["ControllerRequestBuilder"]
