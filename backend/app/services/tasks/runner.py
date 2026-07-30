from __future__ import annotations

from app.infra.database import get_database
from app.services.agent_runtime.contracts import ExecutionContext, PlanReceipt
from app.services.agent_runtime.runtime import SystemRuntime
from app.services.tasks.contracts import (
    TaskFailureProjection,
    TaskPendingClarification,
    TaskPlanVersion,
    TaskStateSnapshot,
)
from app.services.tasks.execution_ledger import PostgresExecutionLedger
from app.services.tasks.plan_compiler import (
    TaskPlanCompilation,
    TaskPlanCompiler,
)
from app.services.tasks.receipt_reconciler import (
    TaskReceiptReconciler,
)
from app.services.tasks.repository import (
    TaskConflictError,
    TaskLeaseError,
    TaskRepository,
)
from app.services.tasks.runner_contracts import (
    TaskResumeCommand,
    TaskRunCommand,
    TaskRunReceipt,
)


class TaskRunner:
    """Run one leased task without planning, publishing, or provider access."""

    def __init__(
        self,
        *,
        repository: TaskRepository | None = None,
        compiler: TaskPlanCompiler | None = None,
        reconciler: TaskReceiptReconciler | None = None,
        runtime: SystemRuntime | None = None,
    ) -> None:
        self._repository = repository or TaskRepository()
        self._compiler = compiler or TaskPlanCompiler()
        self._reconciler = reconciler or TaskReceiptReconciler(
            repository=self._repository
        )
        self._runtime = runtime or SystemRuntime(
            ledger=PostgresExecutionLedger()
        )

    async def run(self, command: TaskRunCommand) -> TaskRunReceipt:
        state = await self._read_owned(command)
        immediate = _terminal_or_paused_receipt(state)
        if immediate is not None:
            return immediate

        try:
            state = await self._claim(command)
        except TaskLeaseError:
            current = await self._read_owned(command)
            immediate = _terminal_or_paused_receipt(current)
            if immediate is not None:
                return immediate
            return TaskRunReceipt(
                task_id=command.task_id,
                status="yielded",
                task_state=current,
            )

        plan_receipts: list[PlanReceipt] = []
        completed_step_keys: list[str] = []
        try:
            version = await self._current_version(state)
        except Exception:
            return await self._fail(
                command=command,
                state=state,
                version=None,
                code="task_plan_missing",
                message="任务缺少可验证的当前计划版本。",
                plan_receipts=plan_receipts,
                completed_step_keys=completed_step_keys,
            )

        for _ in range(command.max_batches):
            try:
                reconciliation = await self._reconcile(
                    state=state,
                    version=version,
                    owner=command.lease_owner,
                )
                state = reconciliation.state
                completed_step_keys = reconciliation.completed_step_keys
                compilation = self._compiler.compile_next(
                    version,
                    completed_step_keys=set(completed_step_keys),
                )
            except TaskLeaseError:
                return await self._current_outcome(
                    command=command,
                    plan_receipts=plan_receipts,
                    completed_step_keys=completed_step_keys,
                )
            except Exception:
                return await self._fail(
                    command=command,
                    state=state,
                    version=version,
                    code="task_reconciliation_failed",
                    message="任务回执与当前计划无法安全对齐。",
                    plan_receipts=plan_receipts,
                    completed_step_keys=completed_step_keys,
                )
            terminal = await self._handle_compilation_terminal(
                command=command,
                state=state,
                version=version,
                compilation=compilation,
                plan_receipts=plan_receipts,
                completed_step_keys=completed_step_keys,
            )
            if terminal is not None:
                return terminal
            if compilation.plan is None:
                return await self._fail(
                    command=command,
                    state=state,
                    version=version,
                    code="task_compiler_missing_plan",
                    message="任务没有形成可执行批次。",
                    plan_receipts=plan_receipts,
                    completed_step_keys=completed_step_keys,
                )

            try:
                state = await self._renew(command, state)
            except (TaskLeaseError, TaskConflictError):
                return await self._current_outcome(
                    command=command,
                    plan_receipts=plan_receipts,
                    completed_step_keys=completed_step_keys,
                )
            context = ExecutionContext(
                user_id=state.user_id,
                thread_id=state.thread_id,
                request_id=command.request_id,
                task_id=state.task_id,
                plan_version_id=version.id,
                lease_owner=command.lease_owner,
            )
            try:
                receipt = await self._runtime.execute(
                    compilation.plan,
                    context=context,
                )
            except Exception:
                return await self._fail(
                    command=command,
                    state=state,
                    version=version,
                    code="task_runtime_failed",
                    message="任务执行回执未能安全完成。",
                    plan_receipts=plan_receipts,
                    completed_step_keys=completed_step_keys,
                )
            plan_receipts.append(receipt)

            try:
                reconciliation = await self._reconcile(
                    state=state,
                    version=version,
                    owner=command.lease_owner,
                )
            except TaskLeaseError:
                return await self._current_outcome(
                    command=command,
                    plan_receipts=plan_receipts,
                    completed_step_keys=completed_step_keys,
                )
            state = reconciliation.state
            completed_step_keys = reconciliation.completed_step_keys

            if receipt.status == "waiting":
                return await self._wait(
                    command=command,
                    state=state,
                    version=version,
                    receipt=receipt,
                    receipt_refs_by_action=(
                        reconciliation.receipt_refs_by_action
                    ),
                    plan_receipts=plan_receipts,
                    completed_step_keys=completed_step_keys,
                )
            if receipt.status != "completed":
                return await self._fail_from_receipt(
                    command=command,
                    state=state,
                    version=version,
                    receipt=receipt,
                    receipt_refs_by_action=(
                        reconciliation.receipt_refs_by_action
                    ),
                    plan_receipts=plan_receipts,
                    completed_step_keys=completed_step_keys,
                )

            after_batch = self._compiler.compile_next(
                version,
                completed_step_keys=set(completed_step_keys),
            )
            if after_batch.status == "completed":
                return await self._complete(
                    command=command,
                    state=state,
                    plan_receipts=plan_receipts,
                    completed_step_keys=completed_step_keys,
                )

        return await self._yield(
            command=command,
            state=state,
            plan_receipts=plan_receipts,
            completed_step_keys=completed_step_keys,
        )

    async def resume(
        self,
        command: TaskResumeCommand,
    ) -> TaskRunReceipt:
        database = get_database()
        async with database.session() as session:
            await self._repository.claim_resume(
                session,
                command.task_id,
                user_id=command.user_id,
                thread_id=command.thread_id,
                plan_version_id=command.plan_version_id,
                expected_state_version=command.expected_state_version,
                owner=command.lease_owner,
                lease_seconds=command.lease_seconds,
            )
        return await self.run(command.as_run_command())

    async def _read_owned(
        self,
        command: TaskRunCommand,
    ) -> TaskStateSnapshot:
        database = get_database()
        async with database.session() as session:
            return await self._repository.get(
                session,
                command.task_id,
                user_id=command.user_id,
                thread_id=command.thread_id,
            )

    async def _claim(
        self,
        command: TaskRunCommand,
    ) -> TaskStateSnapshot:
        database = get_database()
        async with database.session() as session:
            return await self._repository.claim_start_or_recover(
                session,
                command.task_id,
                user_id=command.user_id,
                thread_id=command.thread_id,
                owner=command.lease_owner,
                lease_seconds=command.lease_seconds,
            )

    async def _current_version(
        self,
        state: TaskStateSnapshot,
    ) -> TaskPlanVersion:
        if state.current_plan_version_id is None:
            raise RuntimeError("task has no current plan version")
        database = get_database()
        async with database.session() as session:
            version = await self._repository.get_plan_version(
                session,
                state.current_plan_version_id,
            )
        if version.task_id != state.task_id:
            raise RuntimeError("current task plan ownership mismatch")
        return version

    async def _renew(
        self,
        command: TaskRunCommand,
        state: TaskStateSnapshot,
    ) -> TaskStateSnapshot:
        database = get_database()
        async with database.session() as session:
            return await self._repository.renew_lease(
                session,
                state.task_id,
                owner=command.lease_owner,
                expected_state_version=state.state_version,
                lease_seconds=command.lease_seconds,
            )

    async def _reconcile(
        self,
        *,
        state: TaskStateSnapshot,
        version: TaskPlanVersion,
        owner: str,
    ):
        database = get_database()
        async with database.session() as session:
            return await self._reconciler.reconcile(
                session,
                task_id=state.task_id,
                owner=owner,
                version=version,
            )

    async def _handle_compilation_terminal(
        self,
        *,
        command: TaskRunCommand,
        state: TaskStateSnapshot,
        version: TaskPlanVersion,
        compilation: TaskPlanCompilation,
        plan_receipts: list[PlanReceipt],
        completed_step_keys: list[str],
    ) -> TaskRunReceipt | None:
        if compilation.status == "completed":
            return await self._complete(
                command=command,
                state=state,
                plan_receipts=plan_receipts,
                completed_step_keys=completed_step_keys,
            )
        if compilation.status == "blocked":
            return await self._fail(
                command=command,
                state=state,
                version=version,
                code="task_plan_blocked",
                message="任务计划没有可继续执行的步骤。",
                plan_receipts=plan_receipts,
                completed_step_keys=completed_step_keys,
            )
        return None

    async def _complete(
        self,
        *,
        command: TaskRunCommand,
        state: TaskStateSnapshot,
        plan_receipts: list[PlanReceipt],
        completed_step_keys: list[str],
    ) -> TaskRunReceipt:
        database = get_database()
        try:
            async with database.session() as session:
                completed = await self._repository.transition(
                    session,
                    state.task_id,
                    owner=command.lease_owner,
                    expected_state_version=state.state_version,
                    status="completed",
                )
        except (TaskLeaseError, TaskConflictError):
            return await self._current_outcome(
                command=command,
                plan_receipts=plan_receipts,
                completed_step_keys=completed_step_keys,
            )
        return TaskRunReceipt(
            task_id=state.task_id,
            status="completed",
            task_state=completed,
            plan_receipts=plan_receipts,
            completed_step_keys=completed_step_keys,
        )

    async def _wait(
        self,
        *,
        command: TaskRunCommand,
        state: TaskStateSnapshot,
        version: TaskPlanVersion,
        receipt: PlanReceipt,
        receipt_refs_by_action: dict[str, str],
        plan_receipts: list[PlanReceipt],
        completed_step_keys: list[str],
    ) -> TaskRunReceipt:
        action = next(
            (item for item in receipt.actions if item.status == "waiting"),
            None,
        )
        question = _waiting_question(action)
        step_key = (
            _step_key_for_action(version, action.action_id)
            if action is not None
            else None
        )
        pending = TaskPendingClarification(
            question=question,
            step_key=step_key,
            blocked_plan_version_id=version.id,
            blocked_action_id=action.action_id if action is not None else None,
            receipt_ref=(
                receipt_refs_by_action.get(action.action_id)
                if action is not None
                else None
            ),
        )
        database = get_database()
        try:
            async with database.session() as session:
                waiting = await self._repository.transition(
                    session,
                    state.task_id,
                    owner=command.lease_owner,
                    expected_state_version=state.state_version,
                    status="waiting",
                    waiting_reason="clarification_required",
                    pending_clarification=pending,
                )
        except (TaskLeaseError, TaskConflictError):
            return await self._current_outcome(
                command=command,
                plan_receipts=plan_receipts,
                completed_step_keys=completed_step_keys,
            )
        return TaskRunReceipt(
            task_id=state.task_id,
            status="waiting",
            task_state=waiting,
            plan_receipts=plan_receipts,
            completed_step_keys=completed_step_keys,
            waiting_question=question,
        )

    async def _fail_from_receipt(
        self,
        *,
        command: TaskRunCommand,
        state: TaskStateSnapshot,
        version: TaskPlanVersion,
        receipt: PlanReceipt,
        receipt_refs_by_action: dict[str, str],
        plan_receipts: list[PlanReceipt],
        completed_step_keys: list[str],
    ) -> TaskRunReceipt:
        failed_action_ids = [
            item.action_id
            for item in receipt.actions
            if item.status != "completed"
        ]
        return await self._fail(
            command=command,
            state=state,
            version=version,
            code=f"task_plan_{receipt.status}",
            message="一个或多个任务步骤未能完成。",
            plan_receipts=plan_receipts,
            completed_step_keys=completed_step_keys,
            failed_action_ids=failed_action_ids,
            receipt_refs=[
                receipt_refs_by_action[action_id]
                for action_id in failed_action_ids
                if action_id in receipt_refs_by_action
            ],
        )

    async def _fail(
        self,
        *,
        command: TaskRunCommand,
        state: TaskStateSnapshot,
        version: TaskPlanVersion | None,
        code: str,
        message: str,
        plan_receipts: list[PlanReceipt],
        completed_step_keys: list[str],
        failed_action_ids: list[str] | None = None,
        receipt_refs: list[str] | None = None,
    ) -> TaskRunReceipt:
        failure = TaskFailureProjection(
            code=code,
            message=message,
            failed_plan_version_id=version.id if version is not None else None,
            failed_action_ids=failed_action_ids or [],
            receipt_refs=receipt_refs or [],
            retryable=False,
        )
        database = get_database()
        try:
            async with database.session() as session:
                failed = await self._repository.transition(
                    session,
                    state.task_id,
                    owner=command.lease_owner,
                    expected_state_version=state.state_version,
                    status="failed",
                    terminal_error=failure,
                )
        except (TaskLeaseError, TaskConflictError):
            return await self._current_outcome(
                command=command,
                plan_receipts=plan_receipts,
                completed_step_keys=completed_step_keys,
            )
        return TaskRunReceipt(
            task_id=state.task_id,
            status="failed",
            task_state=failed,
            plan_receipts=plan_receipts,
            completed_step_keys=completed_step_keys,
        )

    async def _yield(
        self,
        *,
        command: TaskRunCommand,
        state: TaskStateSnapshot,
        plan_receipts: list[PlanReceipt],
        completed_step_keys: list[str],
    ) -> TaskRunReceipt:
        database = get_database()
        try:
            async with database.session() as session:
                yielded = await self._repository.release_lease(
                    session,
                    state.task_id,
                    owner=command.lease_owner,
                    expected_state_version=state.state_version,
                )
        except (TaskLeaseError, TaskConflictError):
            return await self._current_outcome(
                command=command,
                plan_receipts=plan_receipts,
                completed_step_keys=completed_step_keys,
            )
        return TaskRunReceipt(
            task_id=state.task_id,
            status="yielded",
            task_state=yielded,
            plan_receipts=plan_receipts,
            completed_step_keys=completed_step_keys,
        )

    async def _current_outcome(
        self,
        *,
        command: TaskRunCommand,
        plan_receipts: list[PlanReceipt],
        completed_step_keys: list[str],
    ) -> TaskRunReceipt:
        current = await self._read_owned(command)
        immediate = _terminal_or_paused_receipt(current)
        if immediate is not None:
            return immediate.model_copy(
                update={
                    "plan_receipts": plan_receipts,
                    "completed_step_keys": completed_step_keys,
                }
            )
        return TaskRunReceipt(
            task_id=command.task_id,
            status="yielded",
            task_state=current,
            plan_receipts=plan_receipts,
            completed_step_keys=completed_step_keys,
        )


def _terminal_or_paused_receipt(
    state: TaskStateSnapshot,
) -> TaskRunReceipt | None:
    if state.status == "completed":
        return TaskRunReceipt(
            task_id=state.task_id,
            status="completed",
            task_state=state,
        )
    if state.status == "waiting":
        question = (
            state.pending_clarification.question
            if state.pending_clarification is not None
            else None
        )
        return TaskRunReceipt(
            task_id=state.task_id,
            status="waiting",
            task_state=state,
            waiting_question=question,
        )
    if state.status in {"failed", "cancelled"}:
        return TaskRunReceipt(
            task_id=state.task_id,
            status="failed",
            task_state=state,
        )
    return None


def _waiting_question(action) -> str:
    if action is not None and isinstance(action.output, dict):
        for key in ("clarification_question", "question"):
            value = str(action.output.get(key) or "").strip()
            if value:
                return value[:4_000]
    return "任务需要补充信息后才能继续。"


def _step_key_for_action(
    version: TaskPlanVersion,
    action_id: str,
) -> str | None:
    for step in version.draft.steps:
        if (
            TaskPlanCompiler.action_id(
                task_id=version.task_id,
                plan_version_id=version.id,
                step_key=step.step_key,
            )
            == action_id
        ):
            return step.step_key
    return None


__all__ = ["TaskRunner"]
