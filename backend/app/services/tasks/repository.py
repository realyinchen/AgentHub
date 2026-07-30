from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Literal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.chat import Conversation
from app.models.task import TaskPlanVersionRecord, TaskStateRecord
from app.services.tasks.contracts import (
    TaskCreationRecord,
    TaskFailureProjection,
    TaskPendingClarification,
    TaskPlanDraft,
    TaskPlanRevisionRecord,
    TaskPlanVersion,
    TaskReceiptProjection,
    TaskStateSnapshot,
    TaskStatus,
    ValidatedTaskPlanDraft,
    ValidatedTaskPlanRevision,
)


_TERMINAL = frozenset({"completed", "cancelled"})
_ACTIVE = frozenset({"pending", "running", "waiting", "failed"})
_TRANSITIONS: dict[str, frozenset[str]] = {
    "pending": frozenset({"running", "cancelled"}),
    "running": frozenset({"waiting", "completed", "failed", "cancelled"}),
    "waiting": frozenset({"running", "failed", "cancelled"}),
    "failed": frozenset({"running", "cancelled"}),
    "completed": frozenset(),
    "cancelled": frozenset(),
}


class TaskStateError(RuntimeError):
    pass


class TaskNotFoundError(TaskStateError):
    pass


class TaskLeaseError(TaskStateError):
    pass


class TaskConflictError(TaskStateError):
    pass


class TaskRepository:
    """Own task persistence, state transitions, optimistic versioning, and lease."""

    async def create_v1(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        thread_id: UUID,
        origin_request_id: str,
        validated: ValidatedTaskPlanDraft,
        source: str = "controller",
    ) -> TaskCreationRecord:
        draft = validated.draft
        request_id = _clean_request_id(origin_request_id)
        conversation = await db.execute(
            select(Conversation.thread_id)
            .where(
                Conversation.thread_id == thread_id,
                Conversation.user_id == user_id,
                Conversation.is_deleted.is_(False),
            )
            .with_for_update()
        )
        if conversation.scalar_one_or_none() is None:
            raise TaskNotFoundError(
                "conversation not found or ownership mismatch"
            )

        existing_result = await db.execute(
            select(TaskStateRecord)
            .where(
                TaskStateRecord.thread_id == thread_id,
                TaskStateRecord.origin_request_id == request_id,
            )
            .with_for_update()
        )
        existing = existing_result.scalar_one_or_none()
        if existing is not None:
            if existing.current_plan_version_id is None:
                raise TaskConflictError(
                    "idempotent task has no current plan version"
                )
            plan = await self.get_plan_version(
                db,
                existing.current_plan_version_id,
            )
            if plan.draft.model_dump(mode="json") != draft.model_dump(
                mode="json"
            ):
                raise TaskConflictError(
                    "origin request was already used for a different task plan"
                )
            return TaskCreationRecord(
                created=False,
                state=_state_snapshot(existing),
                plan_version=plan,
            )

        state = TaskStateRecord(
            user_id=user_id,
            thread_id=thread_id,
            origin_request_id=request_id,
            status="pending",
            state_version=0,
        )
        db.add(state)
        await db.flush()
        version = TaskPlanVersionRecord(
            task_id=state.task_id,
            version_no=1,
            previous_version_id=None,
            plan_json=draft.model_dump(mode="json"),
            source=source,
            origin_request_id=request_id,
        )
        db.add(version)
        await db.flush()
        state.current_plan_version_id = version.id
        state.state_version = 1
        await db.flush()
        await db.refresh(state)
        await db.refresh(version)
        return TaskCreationRecord(
            created=True,
            state=_state_snapshot(state),
            plan_version=_plan_version(version),
        )

    async def get(
        self,
        db: AsyncSession,
        task_id: UUID,
        *,
        user_id: UUID | None = None,
        thread_id: UUID | None = None,
        for_update: bool = False,
    ) -> TaskStateSnapshot:
        record = await self._state_record(
            db,
            task_id,
            user_id=user_id,
            thread_id=thread_id,
            for_update=for_update,
        )
        return _state_snapshot(record)

    async def get_plan_version(
        self,
        db: AsyncSession,
        plan_version_id: UUID,
    ) -> TaskPlanVersion:
        result = await db.execute(
            select(TaskPlanVersionRecord).where(
                TaskPlanVersionRecord.id == plan_version_id
            )
        )
        record = result.scalar_one_or_none()
        if record is None:
            raise TaskNotFoundError("task plan version not found")
        return _plan_version(record)

    async def lock_conversation(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        thread_id: UUID,
    ) -> None:
        result = await db.execute(
            select(Conversation.thread_id)
            .where(
                Conversation.thread_id == thread_id,
                Conversation.user_id == user_id,
                Conversation.is_deleted.is_(False),
            )
            .with_for_update()
        )
        if result.scalar_one_or_none() is None:
            raise TaskNotFoundError(
                "conversation not found or ownership mismatch"
            )

    async def find_request_plan(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        thread_id: UUID,
        origin_request_id: str,
    ) -> tuple[TaskStateSnapshot, TaskPlanVersion] | None:
        request_id = _clean_request_id(origin_request_id)
        direct = await db.execute(
            select(TaskStateRecord)
            .where(
                TaskStateRecord.user_id == user_id,
                TaskStateRecord.thread_id == thread_id,
                TaskStateRecord.origin_request_id == request_id,
            )
        )
        direct_state = direct.scalar_one_or_none()
        if direct_state is not None:
            if direct_state.current_plan_version_id is None:
                raise TaskConflictError(
                    "idempotent task has no current plan version"
                )
            plan_result = await db.execute(
                select(TaskPlanVersionRecord).where(
                    TaskPlanVersionRecord.task_id
                    == direct_state.task_id,
                    TaskPlanVersionRecord.version_no == 1,
                )
            )
            plan = plan_result.scalar_one_or_none()
            if plan is None:
                raise TaskConflictError(
                    "idempotent task has no initial plan version"
                )
            return _state_snapshot(direct_state), _plan_version(plan)

        revision = await db.execute(
            select(TaskStateRecord, TaskPlanVersionRecord)
            .join(
                TaskPlanVersionRecord,
                TaskPlanVersionRecord.task_id
                == TaskStateRecord.task_id,
            )
            .where(
                TaskStateRecord.user_id == user_id,
                TaskStateRecord.thread_id == thread_id,
                TaskPlanVersionRecord.origin_request_id == request_id,
            )
        )
        rows = revision.all()
        if len(rows) > 1:
            raise TaskConflictError(
                "origin request resolved to multiple task plans"
            )
        if not rows:
            return None
        state, plan = rows[0]
        return _state_snapshot(state), _plan_version(plan)

    async def active_for_thread(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        thread_id: UUID,
        for_update: bool = True,
    ) -> list[TaskStateSnapshot]:
        query = (
            select(TaskStateRecord)
            .where(
                TaskStateRecord.user_id == user_id,
                TaskStateRecord.thread_id == thread_id,
                TaskStateRecord.status.in_(_ACTIVE),
            )
            .order_by(TaskStateRecord.created_at)
        )
        if for_update:
            query = query.with_for_update()
        result = await db.execute(query)
        return [_state_snapshot(record) for record in result.scalars().all()]

    async def claim_start_or_recover(
        self,
        db: AsyncSession,
        task_id: UUID,
        *,
        user_id: UUID,
        thread_id: UUID,
        owner: str,
        lease_seconds: int = 30,
    ) -> TaskStateSnapshot:
        record = await self._state_record(
            db,
            task_id,
            user_id=user_id,
            thread_id=thread_id,
            for_update=True,
        )
        now = _utc_now()
        if record.status in _TERMINAL:
            raise TaskLeaseError("terminal task cannot acquire a lease")
        if record.status in {"waiting", "failed"}:
            raise TaskLeaseError(
                "waiting or failed task requires a validated new plan version"
            )
        if record.status not in {"pending", "running"}:
            raise TaskLeaseError(
                f"task status cannot be claimed: {record.status}"
            )
        if (
            record.lease_owner
            and record.lease_owner != owner
            and record.lease_expires_at
            and record.lease_expires_at > now
        ):
            raise TaskLeaseError("task lease is held by another worker")
        duration = max(5, min(int(lease_seconds), 300))
        record.lease_owner = _clean_owner(owner)
        record.lease_expires_at = now + timedelta(seconds=duration)
        if record.status == "pending":
            record.status = "running"
        record.state_version += 1
        await db.flush()
        await db.refresh(record)
        return _state_snapshot(record)

    async def renew_lease(
        self,
        db: AsyncSession,
        task_id: UUID,
        *,
        owner: str,
        expected_state_version: int,
        lease_seconds: int = 30,
    ) -> TaskStateSnapshot:
        record = await self._state_record(db, task_id, for_update=True)
        self._assert_version(record, expected_state_version)
        self._assert_lease(record, owner)
        duration = max(5, min(int(lease_seconds), 300))
        record.lease_expires_at = _utc_now() + timedelta(seconds=duration)
        record.state_version += 1
        await db.flush()
        await db.refresh(record)
        return _state_snapshot(record)

    async def transition(
        self,
        db: AsyncSession,
        task_id: UUID,
        *,
        owner: str,
        expected_state_version: int,
        status: TaskStatus,
        waiting_reason: str | None = None,
        pending_clarification: TaskPendingClarification | None = None,
        terminal_error: TaskFailureProjection | None = None,
    ) -> TaskStateSnapshot:
        record = await self._state_record(db, task_id, for_update=True)
        self._assert_version(record, expected_state_version)
        self._assert_lease(record, owner)
        if status not in _TRANSITIONS[record.status]:
            raise TaskStateError(
                f"invalid task transition: {record.status} -> {status}"
            )
        if status == "waiting" and not str(waiting_reason or "").strip():
            raise TaskStateError("waiting task requires waiting_reason")
        if status == "failed" and terminal_error is None:
            raise TaskStateError("failed task requires terminal_error projection")
        record.status = status
        record.waiting_reason = (
            str(waiting_reason).strip() if waiting_reason else None
        )
        record.pending_clarification = (
            pending_clarification.model_dump(mode="json")
            if pending_clarification is not None
            else None
        )
        record.terminal_error = (
            terminal_error.model_dump(mode="json")
            if status == "failed" and terminal_error is not None
            else None
        )
        if status in {"waiting", "completed", "failed", "cancelled"}:
            record.lease_owner = None
            record.lease_expires_at = None
            record.current_action_id = None
        record.state_version += 1
        await db.flush()
        await db.refresh(record)
        return _state_snapshot(record)

    async def append_validated_version(
        self,
        db: AsyncSession,
        task_id: UUID,
        *,
        user_id: UUID,
        thread_id: UUID,
        origin_request_id: str,
        revision: ValidatedTaskPlanRevision,
        source: Literal["controller", "recovery", "operator"],
    ) -> TaskPlanRevisionRecord:
        draft = revision.validated.draft
        request_id = _clean_request_id(origin_request_id)
        state = await self._state_record(
            db,
            task_id,
            user_id=user_id,
            thread_id=thread_id,
            for_update=True,
        )
        existing_result = await db.execute(
            select(TaskPlanVersionRecord)
            .where(
                TaskPlanVersionRecord.task_id == task_id,
                TaskPlanVersionRecord.origin_request_id == request_id,
            )
            .with_for_update()
        )
        existing = existing_result.scalar_one_or_none()
        if existing is not None:
            if existing.plan_json != draft.model_dump(mode="json"):
                raise TaskConflictError(
                    "origin request was already used for a different revision"
                )
            return TaskPlanRevisionRecord(
                appended=False,
                prior_status=state.status,
                state=_state_snapshot(state),
                plan_version=_plan_version(existing),
            )

        self._assert_version(state, revision.expected_state_version)
        if state.status not in {"pending", "waiting", "failed"}:
            raise TaskStateError(
                f"task status cannot append a plan: {state.status}"
            )
        if state.current_plan_version_id != revision.base_plan_version_id:
            raise TaskConflictError(
                "task current plan changed before revision append"
            )
        latest = await db.execute(
            select(TaskPlanVersionRecord)
            .where(TaskPlanVersionRecord.task_id == task_id)
            .order_by(TaskPlanVersionRecord.version_no.desc())
            .limit(1)
        )
        previous = latest.scalar_one()
        version = TaskPlanVersionRecord(
            task_id=task_id,
            version_no=previous.version_no + 1,
            previous_version_id=previous.id,
            plan_json=draft.model_dump(mode="json"),
            source=source,
            origin_request_id=request_id,
        )
        db.add(version)
        await db.flush()
        state.current_plan_version_id = version.id
        state.state_version += 1
        await db.flush()
        await db.refresh(state)
        await db.refresh(version)
        return TaskPlanRevisionRecord(
            appended=True,
            prior_status=revision.prior_status,
            state=_state_snapshot(state),
            plan_version=_plan_version(version),
        )

    async def claim_resume(
        self,
        db: AsyncSession,
        task_id: UUID,
        *,
        user_id: UUID,
        thread_id: UUID,
        plan_version_id: UUID,
        expected_state_version: int,
        owner: str,
        lease_seconds: int = 30,
    ) -> TaskStateSnapshot:
        state = await self._state_record(
            db,
            task_id,
            user_id=user_id,
            thread_id=thread_id,
            for_update=True,
        )
        self._assert_version(state, expected_state_version)
        if state.status not in {"waiting", "failed"}:
            raise TaskLeaseError(
                "resume requires a waiting or failed task"
            )
        if state.current_plan_version_id != plan_version_id:
            raise TaskConflictError(
                "resume plan is not the current task plan"
            )
        plan = await self.get_plan_version(db, plan_version_id)
        blocked_version_id = None
        if state.status == "waiting" and state.pending_clarification:
            blocked_version_id = TaskPendingClarification.model_validate(
                state.pending_clarification
            ).blocked_plan_version_id
        elif state.status == "failed" and state.terminal_error:
            blocked_version_id = TaskFailureProjection.model_validate(
                state.terminal_error
            ).failed_plan_version_id
        if (
            blocked_version_id is None
            or plan.previous_version_id != blocked_version_id
        ):
            raise TaskLeaseError(
                "resume requires a new version after the blocked plan"
            )
        duration = max(5, min(int(lease_seconds), 300))
        state.status = "running"
        state.waiting_reason = None
        state.pending_clarification = None
        state.terminal_error = None
        state.current_action_id = None
        state.lease_owner = _clean_owner(owner)
        state.lease_expires_at = _utc_now() + timedelta(seconds=duration)
        state.state_version += 1
        await db.flush()
        await db.refresh(state)
        return _state_snapshot(state)

    async def cancel_active_for_thread(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        thread_id: UUID,
    ) -> TaskStateSnapshot | None:
        await self.lock_conversation(
            db,
            user_id=user_id,
            thread_id=thread_id,
        )
        active = await self.active_for_thread(
            db,
            user_id=user_id,
            thread_id=thread_id,
        )
        if not active:
            return None
        if len(active) != 1:
            raise TaskConflictError(
                "multiple active tasks require operator reconciliation"
            )
        record = await self._state_record(
            db,
            active[0].task_id,
            user_id=user_id,
            thread_id=thread_id,
            for_update=True,
        )
        record.status = "cancelled"
        record.waiting_reason = None
        record.pending_clarification = None
        record.terminal_error = None
        record.current_action_id = None
        record.lease_owner = None
        record.lease_expires_at = None
        record.state_version += 1
        await db.flush()
        await db.refresh(record)
        return _state_snapshot(record)

    async def project_receipts(
        self,
        db: AsyncSession,
        task_id: UUID,
        *,
        owner: str,
        projections: list[TaskReceiptProjection],
    ) -> TaskStateSnapshot:
        state = await self._state_record(db, task_id, for_update=True)
        self._assert_lease(state, owner)
        projected = list(state.projected_receipt_refs or [])
        completed = list(state.completed_receipt_refs or [])
        seen_input: set[str] = set()
        changed = False
        last_action_id: str | None = None
        for projection in projections:
            if projection.receipt_ref in seen_input:
                raise TaskConflictError(
                    "receipt projection batch contains duplicate refs"
                )
            seen_input.add(projection.receipt_ref)
            if projection.receipt_ref in projected:
                if (
                    projection.completed
                    and projection.receipt_ref not in completed
                ):
                    raise TaskConflictError(
                        "projected receipt completion status changed"
                    )
                continue
            projected.append(projection.receipt_ref)
            if projection.completed:
                completed.append(projection.receipt_ref)
            changed = True
            last_action_id = projection.action_id
        if not changed:
            return _state_snapshot(state)
        state.projected_receipt_refs = projected
        state.completed_receipt_refs = completed
        state.recovery_cursor = len(projected)
        state.state_version += 1
        state.current_action_id = last_action_id
        await db.flush()
        await db.refresh(state)
        return _state_snapshot(state)

    async def release_lease(
        self,
        db: AsyncSession,
        task_id: UUID,
        *,
        owner: str,
        expected_state_version: int,
    ) -> TaskStateSnapshot:
        state = await self._state_record(db, task_id, for_update=True)
        self._assert_version(state, expected_state_version)
        self._assert_lease(state, owner)
        if state.status != "running":
            raise TaskStateError("only a running task can release its lease")
        state.lease_owner = None
        state.lease_expires_at = None
        state.current_action_id = None
        state.state_version += 1
        await db.flush()
        await db.refresh(state)
        return _state_snapshot(state)

    async def _state_record(
        self,
        db: AsyncSession,
        task_id: UUID,
        *,
        user_id: UUID | None = None,
        thread_id: UUID | None = None,
        for_update: bool = False,
    ) -> TaskStateRecord:
        query = select(TaskStateRecord).where(TaskStateRecord.task_id == task_id)
        if user_id is not None:
            query = query.where(TaskStateRecord.user_id == user_id)
        if thread_id is not None:
            query = query.where(TaskStateRecord.thread_id == thread_id)
        if for_update:
            query = query.with_for_update()
        result = await db.execute(query)
        record = result.scalar_one_or_none()
        if record is None:
            raise TaskNotFoundError("task not found or ownership mismatch")
        return record

    @staticmethod
    def _assert_version(
        record: TaskStateRecord,
        expected_state_version: int,
    ) -> None:
        if record.state_version != expected_state_version:
            raise TaskConflictError(
                "task state_version changed; reload before updating"
            )

    @staticmethod
    def _assert_lease(record: TaskStateRecord, owner: str) -> None:
        now = _utc_now()
        if (
            record.lease_owner != owner
            or record.lease_expires_at is None
            or record.lease_expires_at <= now
        ):
            raise TaskLeaseError("valid task lease is required")


def _state_snapshot(record: TaskStateRecord) -> TaskStateSnapshot:
    return TaskStateSnapshot(
        task_id=record.task_id,
        user_id=record.user_id,
        thread_id=record.thread_id,
        origin_request_id=record.origin_request_id,
        status=record.status,
        current_plan_version_id=record.current_plan_version_id,
        current_action_id=record.current_action_id,
        completed_receipt_refs=list(record.completed_receipt_refs or []),
        projected_receipt_refs=list(record.projected_receipt_refs or []),
        waiting_reason=record.waiting_reason,
        pending_clarification=record.pending_clarification,
        recovery_cursor=record.recovery_cursor,
        lease_owner=record.lease_owner,
        lease_expires_at=record.lease_expires_at,
        terminal_error=record.terminal_error,
        state_version=record.state_version,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


def _plan_version(record: TaskPlanVersionRecord) -> TaskPlanVersion:
    return TaskPlanVersion(
        id=record.id,
        task_id=record.task_id,
        version_no=record.version_no,
        previous_version_id=record.previous_version_id,
        draft=TaskPlanDraft.model_validate(record.plan_json),
        source=record.source,
        origin_request_id=record.origin_request_id,
        created_at=record.created_at,
    )


def _clean_owner(owner: str) -> str:
    value = str(owner or "").strip()
    if not value or len(value) > 128:
        raise TaskLeaseError("lease owner must be 1..128 characters")
    return value


def _clean_request_id(request_id: str) -> str:
    value = str(request_id or "").strip()
    if not value or len(value) > 128:
        raise TaskConflictError(
            "origin request id must be 1..128 characters"
        )
    return value


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


__all__ = [
    "TaskConflictError",
    "TaskLeaseError",
    "TaskNotFoundError",
    "TaskRepository",
    "TaskStateError",
]
