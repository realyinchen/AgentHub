"""Append-only persistence for embedding calibration reports."""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.infra.database.database import PostgresDatabase
from app.infra.embedding_spaces.calibration_contracts import (
    CalibrationScoreDistribution,
    EmbeddingCalibrationReportDraft,
    EmbeddingCalibrationReportRecord,
    EmbeddingCalibrationResult,
    GenerationValidationChecks,
)


class EmbeddingCalibrationRepository:
    """Persist and read immutable reports; never changes active bindings."""

    def __init__(self, database: PostgresDatabase) -> None:
        self._database = database

    async def append(
        self,
        draft: EmbeddingCalibrationReportDraft,
    ) -> EmbeddingCalibrationReportRecord:
        async with self._database.session() as session:
            return await self.append_in_session(session, draft)

    async def append_in_session(
        self,
        session: AsyncSession,
        draft: EmbeddingCalibrationReportDraft,
    ) -> EmbeddingCalibrationReportRecord:
        """Append through the caller's transaction for atomic cutover."""

        result = draft.result
        inserted = await session.execute(
            text(
                """
                INSERT INTO public.embedding_calibration_reports (
                    space_id,
                    report_fingerprint,
                    dataset_version,
                    dataset_sha256,
                    source_watermark,
                    threshold,
                    sample_count,
                    positive_count,
                    negative_count,
                    precision_score,
                    recall_score,
                    f1_score,
                    score_distribution,
                    validation_checks,
                    status,
                    failure_codes
                )
                VALUES (
                    :space_id,
                    :report_fingerprint,
                    :dataset_version,
                    :dataset_sha256,
                    :source_watermark,
                    :threshold,
                    :sample_count,
                    :positive_count,
                    :negative_count,
                    :precision_score,
                    :recall_score,
                    :f1_score,
                    CAST(:score_distribution AS JSONB),
                    CAST(:validation_checks AS JSONB),
                    :status,
                    CAST(:failure_codes AS JSONB)
                )
                ON CONFLICT DO NOTHING
                RETURNING *
                """
            ),
            {
                "space_id": draft.space_id,
                "report_fingerprint": draft.report_fingerprint,
                "dataset_version": result.dataset_version,
                "dataset_sha256": result.dataset_sha256,
                "source_watermark": draft.source_watermark,
                "threshold": result.threshold,
                "sample_count": result.sample_count,
                "positive_count": result.positive_count,
                "negative_count": result.negative_count,
                "precision_score": result.precision_score,
                "recall_score": result.recall_score,
                "f1_score": result.f1_score,
                "score_distribution": json.dumps(
                    result.score_distribution.model_dump(mode="json")
                ),
                "validation_checks": json.dumps(
                    result.validation_checks.model_dump(mode="json")
                ),
                "status": result.status,
                "failure_codes": json.dumps(list(result.failure_codes)),
            },
        )
        row = inserted.mappings().first()
        if row is None:
            existing = await session.execute(
                text(
                    """
                    SELECT *
                    FROM public.embedding_calibration_reports
                    WHERE space_id = :space_id
                      AND dataset_sha256 = :dataset_sha256
                    """
                ),
                {
                    "space_id": draft.space_id,
                    "dataset_sha256": result.dataset_sha256,
                },
            )
            row = existing.mappings().one()
            if row["report_fingerprint"] != draft.report_fingerprint:
                raise RuntimeError("embedding_calibration_space_dataset_conflict")
        return calibration_report_from_row(row)

    async def get(
        self,
        report_id: UUID,
    ) -> EmbeddingCalibrationReportRecord | None:
        async with self._database.session() as session:
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
        return calibration_report_from_row(row) if row is not None else None

    async def get_latest_passed(
        self,
        *,
        space_id: UUID,
        dataset_sha256: str,
    ) -> EmbeddingCalibrationReportRecord | None:
        async with self._database.session() as session:
            result = await session.execute(
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
                    "space_id": space_id,
                    "dataset_sha256": dataset_sha256,
                },
            )
            row = result.mappings().first()
        return calibration_report_from_row(row) if row is not None else None


def calibration_report_from_row(row: Any) -> EmbeddingCalibrationReportRecord:
    distribution = _json_object(row["score_distribution"])
    checks = _json_object(row["validation_checks"])
    failure_codes = _json_array(row["failure_codes"])
    result = EmbeddingCalibrationResult(
        dataset_version=row["dataset_version"],
        dataset_sha256=row["dataset_sha256"],
        threshold=float(row["threshold"]),
        sample_count=int(row["sample_count"]),
        positive_count=int(row["positive_count"]),
        negative_count=int(row["negative_count"]),
        precision_score=float(row["precision_score"]),
        recall_score=float(row["recall_score"]),
        f1_score=float(row["f1_score"]),
        score_distribution=CalibrationScoreDistribution.model_validate(distribution),
        validation_checks=GenerationValidationChecks.model_validate(checks),
        status=row["status"],
        failure_codes=tuple(str(code) for code in failure_codes),
    )
    return EmbeddingCalibrationReportRecord(
        id=row["id"],
        space_id=row["space_id"],
        source_watermark=row["source_watermark"],
        report_fingerprint=row["report_fingerprint"],
        result=result,
        created_at=row["created_at"],
    )


def _json_object(value: Any) -> dict[str, Any]:
    if isinstance(value, str):
        value = json.loads(value)
    return dict(value or {})


def _json_array(value: Any) -> list[Any]:
    if isinstance(value, str):
        value = json.loads(value)
    return list(value or [])


__all__ = [
    "EmbeddingCalibrationRepository",
    "calibration_report_from_row",
]
