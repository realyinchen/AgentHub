"""Atomic, calibrated activation and rollback for embedding generations."""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.infra.database.database import PostgresDatabase
from app.infra.embedding_spaces.calibration_contracts import (
    EmbeddingActivationCommand,
    EmbeddingActivationReceipt,
    EmbeddingActivationResult,
    EmbeddingCalibrationReportRecord,
    EmbeddingRollbackCommand,
)
from app.infra.embedding_spaces.calibration_repository import (
    EmbeddingCalibrationRepository,
    calibration_report_from_row,
)


class EmbeddingGenerationActivator:
    """The only validated writer for active embedding-space bindings."""

    def __init__(self, database: PostgresDatabase) -> None:
        self._database = database
        self._reports = EmbeddingCalibrationRepository(database)

    async def activate(
        self,
        command: EmbeddingActivationCommand,
    ) -> EmbeddingActivationResult:
        async with self._database.session() as session:
            await _lock_purpose(session, command.purpose)
            existing = await _get_receipt_by_key(session, command.idempotency_key)
            if existing is not None:
                receipt = activation_receipt_from_row(existing)
                _assert_idempotent_activation(receipt, command)
                report = await _get_report(
                    session,
                    report_id=receipt.calibration_report_id,
                )
                _validate_report(
                    report,
                    purpose=command.purpose,
                    space_id=receipt.to_space_id,
                    expected_dataset_sha256=command.expected_dataset_sha256,
                )
                if report["report_fingerprint"] != (command.report.report_fingerprint):
                    raise RuntimeError("embedding_activation_idempotency_conflict")
                return EmbeddingActivationResult(
                    report=calibration_report_from_row(report),
                    receipt=receipt,
                )

            candidate = await _get_space_for_update(
                session,
                space_id=command.to_space_id,
                purpose=command.purpose,
            )
            if candidate["status"] not in {"ready", "active"}:
                raise RuntimeError("embedding_candidate_not_ready")
            report = await self._reports.append_in_session(
                session,
                command.report,
            )
            _validate_report_record(
                report,
                purpose=command.purpose,
                space_id=command.to_space_id,
                expected_dataset_sha256=command.expected_dataset_sha256,
            )
            current_space_id = await _get_active_space_id(
                session,
                command.purpose,
            )
            if current_space_id == command.to_space_id:
                raise RuntimeError("embedding_generation_already_active")
            receipt = await _switch(
                session,
                purpose=command.purpose,
                action="activate",
                from_space_id=current_space_id,
                to_space_id=command.to_space_id,
                calibration_report_id=report.id,
                idempotency_key=command.idempotency_key,
                source_commit_sha=command.source_commit_sha,
                reason=command.reason,
            )
            return EmbeddingActivationResult(report=report, receipt=receipt)

    async def rollback(
        self,
        command: EmbeddingRollbackCommand,
    ) -> EmbeddingActivationReceipt:
        async with self._database.session() as session:
            await _lock_purpose(session, command.purpose)
            existing = await _get_receipt_by_key(session, command.idempotency_key)
            if existing is not None:
                receipt = activation_receipt_from_row(existing)
                _assert_idempotent_rollback(receipt, command)
                report = await _get_report(
                    session,
                    report_id=receipt.calibration_report_id,
                )
                _validate_report(
                    report,
                    purpose=command.purpose,
                    space_id=receipt.to_space_id,
                    expected_dataset_sha256=command.expected_dataset_sha256,
                )
                return receipt

            current_space_id = await _get_active_space_id(
                session,
                command.purpose,
            )
            if current_space_id is None:
                raise RuntimeError("embedding_active_generation_missing")
            previous_result = await session.execute(
                text(
                    """
                    SELECT from_space_id
                    FROM public.embedding_space_activations
                    WHERE purpose = :purpose
                      AND to_space_id = :current_space_id
                      AND from_space_id IS NOT NULL
                    ORDER BY created_at DESC, id DESC
                    LIMIT 1
                    """
                ),
                {
                    "purpose": command.purpose,
                    "current_space_id": current_space_id,
                },
            )
            previous_space_id = previous_result.scalar_one_or_none()
            if previous_space_id is None:
                raise RuntimeError("embedding_rollback_target_missing")
            candidate = await _get_space_for_update(
                session,
                space_id=previous_space_id,
                purpose=command.purpose,
            )
            if candidate["status"] not in {"ready", "active"}:
                raise RuntimeError("embedding_rollback_target_not_ready")
            report_result = await session.execute(
                text(
                    """
                    SELECT *
                    FROM public.embedding_calibration_reports
                    WHERE space_id = :space_id
                      AND dataset_sha256 = :dataset_sha256
                      AND status = 'passed'
                    ORDER BY created_at DESC, id DESC
                    LIMIT 1
                    """
                ),
                {
                    "space_id": previous_space_id,
                    "dataset_sha256": command.expected_dataset_sha256,
                },
            )
            report = report_result.mappings().first()
            if report is None:
                raise RuntimeError("embedding_rollback_report_missing")
            _validate_report(
                report,
                purpose=command.purpose,
                space_id=previous_space_id,
                expected_dataset_sha256=command.expected_dataset_sha256,
            )
            return await _switch(
                session,
                purpose=command.purpose,
                action="rollback",
                from_space_id=current_space_id,
                to_space_id=previous_space_id,
                calibration_report_id=report["id"],
                idempotency_key=command.idempotency_key,
                source_commit_sha=command.source_commit_sha,
                reason=command.reason,
            )


async def _lock_purpose(session: AsyncSession, purpose: str) -> None:
    await session.execute(
        text("SELECT pg_advisory_xact_lock(hashtext(:lock_key))"),
        {"lock_key": f"embedding-space:{purpose}"},
    )


async def _get_receipt_by_key(
    session: AsyncSession,
    idempotency_key: str,
) -> Any | None:
    result = await session.execute(
        text(
            """
            SELECT *
            FROM public.embedding_space_activations
            WHERE idempotency_key = :idempotency_key
            """
        ),
        {"idempotency_key": idempotency_key},
    )
    return result.mappings().first()


async def _get_space_for_update(
    session: AsyncSession,
    *,
    space_id: Any,
    purpose: str,
) -> Any:
    result = await session.execute(
        text(
            """
            SELECT *
            FROM public.embedding_spaces
            WHERE id = :space_id
              AND purpose = :purpose
            FOR UPDATE
            """
        ),
        {"space_id": space_id, "purpose": purpose},
    )
    row = result.mappings().first()
    if row is None:
        raise RuntimeError("embedding_generation_not_found")
    return row


async def _get_report(
    session: AsyncSession,
    *,
    report_id: Any,
) -> Any:
    result = await session.execute(
        text(
            """
            SELECT *
            FROM public.embedding_calibration_reports
            WHERE id = :report_id
            """
        ),
        {"report_id": report_id},
    )
    row = result.mappings().first()
    if row is None:
        raise RuntimeError("embedding_calibration_report_not_found")
    return row


def _validate_report(
    report: Any,
    *,
    purpose: str,
    space_id: Any,
    expected_dataset_sha256: str,
) -> None:
    if report["space_id"] != space_id:
        raise RuntimeError("embedding_report_space_mismatch")
    if report["status"] != "passed":
        raise RuntimeError("embedding_calibration_failed")
    if report["dataset_sha256"] != expected_dataset_sha256:
        raise RuntimeError("embedding_calibration_dataset_mismatch")
    checks_value = report["validation_checks"]
    if isinstance(checks_value, str):
        checks_value = json.loads(checks_value)
    checks = dict(checks_value or {})
    required_checks = {
        "dimensions",
        "row_count",
        "single_generation_query",
    }
    if purpose == "memory":
        required_checks.update({"active_fact_filter", "tenant_isolation"})
    if any(checks.get(name) != "passed" for name in required_checks):
        raise RuntimeError("embedding_calibration_checks_failed")


def _validate_report_record(
    report: EmbeddingCalibrationReportRecord,
    *,
    purpose: str,
    space_id: Any,
    expected_dataset_sha256: str,
) -> None:
    if report.space_id != space_id:
        raise RuntimeError("embedding_report_space_mismatch")
    if report.result.status != "passed":
        raise RuntimeError("embedding_calibration_failed")
    if report.result.dataset_sha256 != expected_dataset_sha256:
        raise RuntimeError("embedding_calibration_dataset_mismatch")
    checks = report.result.validation_checks
    required_states = (
        checks.dimensions,
        checks.row_count,
        checks.single_generation_query,
    )
    if purpose == "memory":
        required_states += (
            checks.active_fact_filter,
            checks.tenant_isolation,
        )
    if any(state != "passed" for state in required_states):
        raise RuntimeError("embedding_calibration_checks_failed")


async def _get_active_space_id(
    session: AsyncSession,
    purpose: str,
) -> Any | None:
    result = await session.execute(
        text(
            """
            SELECT active_space_id
            FROM public.embedding_space_bindings
            WHERE purpose = :purpose
            FOR UPDATE
            """
        ),
        {"purpose": purpose},
    )
    return result.scalar_one_or_none()


async def _switch(
    session: AsyncSession,
    *,
    purpose: str,
    action: str,
    from_space_id: Any | None,
    to_space_id: Any,
    calibration_report_id: Any,
    idempotency_key: str,
    source_commit_sha: str,
    reason: str,
) -> EmbeddingActivationReceipt:
    if from_space_id is not None and from_space_id != to_space_id:
        demoted = await session.execute(
            text(
                """
                UPDATE public.embedding_spaces
                SET status = 'ready', updated_at = NOW()
                WHERE id = :from_space_id
                  AND purpose = :purpose
                  AND status = 'active'
                RETURNING id
                """
            ),
            {"from_space_id": from_space_id, "purpose": purpose},
        )
        if demoted.scalar_one_or_none() != from_space_id:
            raise RuntimeError("embedding_active_generation_state_mismatch")
    activated = await session.execute(
        text(
            """
            UPDATE public.embedding_spaces
            SET status = 'active',
                activated_at = COALESCE(activated_at, NOW()),
                updated_at = NOW()
            WHERE id = :to_space_id
              AND purpose = :purpose
            RETURNING id
            """
        ),
        {"to_space_id": to_space_id, "purpose": purpose},
    )
    if activated.scalar_one_or_none() != to_space_id:
        raise RuntimeError("embedding_activation_target_update_failed")
    await session.execute(
        text(
            """
            INSERT INTO public.embedding_space_bindings (
                purpose, active_space_id, updated_at
            )
            VALUES (:purpose, :to_space_id, NOW())
            ON CONFLICT (purpose)
            DO UPDATE SET
                active_space_id = EXCLUDED.active_space_id,
                updated_at = NOW()
            """
        ),
        {"purpose": purpose, "to_space_id": to_space_id},
    )
    inserted = await session.execute(
        text(
            """
            INSERT INTO public.embedding_space_activations (
                purpose,
                action,
                from_space_id,
                to_space_id,
                calibration_report_id,
                idempotency_key,
                source_commit_sha,
                reason
            )
            VALUES (
                :purpose,
                :action,
                :from_space_id,
                :to_space_id,
                :calibration_report_id,
                :idempotency_key,
                :source_commit_sha,
                :reason
            )
            RETURNING *
            """
        ),
        {
            "purpose": purpose,
            "action": action,
            "from_space_id": from_space_id,
            "to_space_id": to_space_id,
            "calibration_report_id": calibration_report_id,
            "idempotency_key": idempotency_key,
            "source_commit_sha": source_commit_sha,
            "reason": reason,
        },
    )
    return activation_receipt_from_row(inserted.mappings().one())


def activation_receipt_from_row(row: Any) -> EmbeddingActivationReceipt:
    return EmbeddingActivationReceipt(
        id=row["id"],
        purpose=row["purpose"],
        action=row["action"],
        from_space_id=row["from_space_id"],
        to_space_id=row["to_space_id"],
        calibration_report_id=row["calibration_report_id"],
        idempotency_key=row["idempotency_key"],
        source_commit_sha=row["source_commit_sha"] or "",
        reason=row["reason"] or "",
        created_at=row["created_at"],
    )


def _assert_idempotent_activation(
    receipt: EmbeddingActivationReceipt,
    command: EmbeddingActivationCommand,
) -> None:
    if (
        receipt.action != "activate"
        or receipt.purpose != command.purpose
        or receipt.to_space_id != command.to_space_id
    ):
        raise RuntimeError("embedding_activation_idempotency_conflict")


def _assert_idempotent_rollback(
    receipt: EmbeddingActivationReceipt,
    command: EmbeddingRollbackCommand,
) -> None:
    if receipt.action != "rollback" or receipt.purpose != command.purpose:
        raise RuntimeError("embedding_rollback_idempotency_conflict")


__all__ = ["EmbeddingGenerationActivator", "activation_receipt_from_row"]
