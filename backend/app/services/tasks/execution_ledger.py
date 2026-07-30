from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from app.infra.database import get_database
from app.models.task import ActionExecutionReceiptRecord
from app.services.agent_runtime.contracts import (
    ActionPlan,
    ActionReceipt,
    ExecutionContext,
    PlannedAction,
)
from app.services.agent_runtime.ledger import action_idempotency_key


class ExecutionReceiptConflict(RuntimeError):
    pass


class PostgresExecutionLedger:
    """Durably deduplicate actions and advance a leased task receipt cursor."""

    async def get(
        self,
        *,
        plan: ActionPlan,
        action: PlannedAction,
        context: ExecutionContext,
    ) -> ActionReceipt | None:
        key = action_idempotency_key(
            plan=plan,
            action=action,
            context=context,
        )
        database = get_database()
        async with database.session() as session:
            record = await _get_record(session, key)
            if record is None:
                return None
            _assert_identity(record, plan, action, context)
            return ActionReceipt.model_validate(record.receipt_json)

    async def record(
        self,
        *,
        plan: ActionPlan,
        action: PlannedAction,
        context: ExecutionContext,
        receipt: ActionReceipt,
    ) -> ActionReceipt:
        key = action_idempotency_key(
            plan=plan,
            action=action,
            context=context,
        )
        payload = receipt.model_dump(mode="json")
        database = get_database()
        existing = None
        async with database.session() as session:
            result = await session.execute(
                insert(ActionExecutionReceiptRecord)
                .values(
                    idempotency_key=key,
                    task_id=context.task_id,
                    plan_version_id=context.plan_version_id,
                    plan_id=plan.plan_id,
                    action_id=action.action_id,
                    request_id=context.request_id,
                    capability=action.capability,
                    operation=action.operation,
                    status=receipt.status,
                    receipt_json=payload,
                )
                .on_conflict_do_nothing(
                    index_elements=["idempotency_key"]
                )
                .returning(ActionExecutionReceiptRecord.id)
            )
            result.scalar_one_or_none()
            record = await _get_record(session, key)
            if record is None:
                raise ExecutionReceiptConflict(
                    "receipt insert completed without a readable record"
                )
            _assert_identity(record, plan, action, context)
            existing = ActionReceipt.model_validate(record.receipt_json)
            if existing.model_dump(mode="json") != payload:
                raise ExecutionReceiptConflict(
                    "idempotency key already has a different receipt"
                )
        return existing


async def _get_record(
    session,
    key: str,
) -> ActionExecutionReceiptRecord | None:
    result = await session.execute(
        select(ActionExecutionReceiptRecord).where(
            ActionExecutionReceiptRecord.idempotency_key == key
        )
    )
    return result.scalar_one_or_none()


def _assert_identity(
    record: ActionExecutionReceiptRecord,
    plan: ActionPlan,
    action: PlannedAction,
    context: ExecutionContext,
) -> None:
    if context.task_id is not None:
        expected = (
            context.task_id,
            context.plan_version_id,
            action.action_id,
            action.capability,
            action.operation,
        )
        actual = (
            record.task_id,
            record.plan_version_id,
            record.action_id,
            record.capability,
            record.operation,
        )
    else:
        expected = (
            context.task_id,
            context.plan_version_id,
            plan.plan_id,
            action.action_id,
            context.request_id,
            action.capability,
            action.operation,
        )
        actual = (
            record.task_id,
            record.plan_version_id,
            record.plan_id,
            record.action_id,
            record.request_id,
            record.capability,
            record.operation,
        )
    if actual != expected:
        raise ExecutionReceiptConflict(
            "receipt identity does not match the requested action"
        )
    receipt = ActionReceipt.model_validate(record.receipt_json)
    if receipt.business_input != action.arguments:
        raise ExecutionReceiptConflict(
            "receipt business input does not match the requested action"
        )


__all__ = ["ExecutionReceiptConflict", "PostgresExecutionLedger"]
