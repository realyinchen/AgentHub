"""Strong contracts for generation-specific embedding calibration."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.infra.embedding_spaces.contracts import EmbeddingPurpose

ValidationState = Literal["passed", "failed", "not_applicable"]
CalibrationStatus = Literal["passed", "failed"]
ActivationAction = Literal["activate", "rollback"]


class EmbeddingCalibrationSample(BaseModel):
    """One labeled semantic-similarity example."""

    model_config = ConfigDict(frozen=True)

    sample_id: str = Field(min_length=1, max_length=128)
    query: str = Field(min_length=1)
    anchor: str = Field(min_length=1)
    relevant: bool


class EmbeddingCalibrationDataset(BaseModel):
    """Versioned calibration corpus with explicit quality gates."""

    model_config = ConfigDict(frozen=True)

    dataset_version: str = Field(min_length=1, max_length=128)
    minimum_precision: float = Field(ge=0.0, le=1.0)
    minimum_recall: float = Field(ge=0.0, le=1.0)
    minimum_samples: int = Field(default=10, ge=2)
    samples: tuple[EmbeddingCalibrationSample, ...] = Field(min_length=2)

    @model_validator(mode="after")
    def validate_labels_and_ids(self) -> "EmbeddingCalibrationDataset":
        sample_ids = [sample.sample_id for sample in self.samples]
        if len(sample_ids) != len(set(sample_ids)):
            raise ValueError("Calibration sample_id values must be unique")
        labels = {sample.relevant for sample in self.samples}
        if labels != {False, True}:
            raise ValueError(
                "Calibration dataset must contain positive and negative samples"
            )
        return self


class CalibrationDatasetArtifact(BaseModel):
    """Validated dataset paired with its canonical content hash."""

    model_config = ConfigDict(frozen=True)

    dataset: EmbeddingCalibrationDataset
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class EmbeddingCalibrationScore(BaseModel):
    """Observed cosine score for one labeled sample."""

    model_config = ConfigDict(frozen=True)

    sample_id: str = Field(min_length=1, max_length=128)
    score: float = Field(ge=-1.0, le=1.0, allow_inf_nan=False)


class EmbeddingCalibrationMeasurement(BaseModel):
    """Provider observations captured before the short cutover window."""

    model_config = ConfigDict(frozen=True)

    observed_dimensions: int = Field(ge=0)
    scores: tuple[EmbeddingCalibrationScore, ...] = ()


class ScoreSummary(BaseModel):
    """Compact immutable distribution summary."""

    model_config = ConfigDict(frozen=True)

    count: int = Field(ge=0)
    minimum: float = Field(ge=-1.0, le=1.0)
    maximum: float = Field(ge=-1.0, le=1.0)
    mean: float = Field(ge=-1.0, le=1.0)


class CalibrationScoreDistribution(BaseModel):
    model_config = ConfigDict(frozen=True)

    positive: ScoreSummary
    negative: ScoreSummary


class GenerationValidationChecks(BaseModel):
    """Quality checks that are independent from similarity labels."""

    model_config = ConfigDict(frozen=True)

    dimensions: ValidationState
    row_count: ValidationState
    active_fact_filter: ValidationState
    tenant_isolation: ValidationState
    single_generation_query: ValidationState


class GenerationValidationEvidence(BaseModel):
    """Measured generation state used to derive validation checks."""

    model_config = ConfigDict(frozen=True)

    purpose: EmbeddingPurpose
    expected_dimensions: int = Field(ge=1)
    observed_dimensions: int = Field(ge=0)
    source_count: int = Field(ge=0)
    embedded_count: int = Field(ge=0)
    stored_count: int = Field(ge=0)
    active_fact_filter: ValidationState = "not_applicable"
    tenant_isolation: ValidationState = "not_applicable"
    single_generation_query: ValidationState

    @model_validator(mode="after")
    def require_memory_isolation_evidence(self) -> "GenerationValidationEvidence":
        if self.purpose == "memory" and (
            self.active_fact_filter == "not_applicable"
            or self.tenant_isolation == "not_applicable"
        ):
            raise ValueError(
                "Memory calibration requires activity-filter and tenant evidence"
            )
        return self

    def checks(self) -> GenerationValidationChecks:
        row_count_matches = (
            self.source_count == self.embedded_count == self.stored_count
        )
        return GenerationValidationChecks(
            dimensions=(
                "passed"
                if self.observed_dimensions == self.expected_dimensions
                else "failed"
            ),
            row_count="passed" if row_count_matches else "failed",
            active_fact_filter=self.active_fact_filter,
            tenant_isolation=self.tenant_isolation,
            single_generation_query=self.single_generation_query,
        )


class EmbeddingCalibrationResult(BaseModel):
    """Pure calibration output before it is bound to a database generation."""

    model_config = ConfigDict(frozen=True)

    dataset_version: str
    dataset_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    threshold: float = Field(ge=-1.0, le=1.0, allow_inf_nan=False)
    sample_count: int = Field(ge=1)
    positive_count: int = Field(ge=1)
    negative_count: int = Field(ge=1)
    precision_score: float = Field(ge=0.0, le=1.0)
    recall_score: float = Field(ge=0.0, le=1.0)
    f1_score: float = Field(ge=0.0, le=1.0)
    score_distribution: CalibrationScoreDistribution
    validation_checks: GenerationValidationChecks
    status: CalibrationStatus
    failure_codes: tuple[str, ...] = ()


class EmbeddingCalibrationReportDraft(BaseModel):
    """Generation-bound immutable report ready for persistence."""

    model_config = ConfigDict(frozen=True)

    space_id: UUID
    source_watermark: datetime
    report_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    result: EmbeddingCalibrationResult

    @field_validator("source_watermark")
    @classmethod
    def require_aware_watermark(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("source_watermark must include a timezone")
        return value


class EmbeddingCalibrationReportRecord(EmbeddingCalibrationReportDraft):
    id: UUID
    created_at: datetime | None = None


class EmbeddingActivationCommand(BaseModel):
    """Validated cutover request. System identity never enters routing."""

    model_config = ConfigDict(frozen=True)

    purpose: EmbeddingPurpose
    to_space_id: UUID
    report: EmbeddingCalibrationReportDraft
    expected_dataset_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    idempotency_key: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_commit_sha: str = Field(default="", pattern=r"^$|^[0-9a-f]{40}$")
    reason: str = Field(default="", max_length=512)

    @model_validator(mode="after")
    def require_matching_report(self) -> "EmbeddingActivationCommand":
        if self.report.space_id != self.to_space_id:
            raise ValueError("activation report must target to_space_id")
        if self.report.result.dataset_sha256 != self.expected_dataset_sha256:
            raise ValueError("activation report dataset hash must match command")
        return self


class EmbeddingRollbackCommand(BaseModel):
    """Audited request to restore the prior validated generation."""

    model_config = ConfigDict(frozen=True)

    purpose: EmbeddingPurpose
    expected_dataset_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    idempotency_key: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_commit_sha: str = Field(default="", pattern=r"^$|^[0-9a-f]{40}$")
    reason: str = Field(default="", max_length=512)


class EmbeddingActivationReceipt(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID
    purpose: EmbeddingPurpose
    action: ActivationAction
    from_space_id: UUID | None
    to_space_id: UUID
    calibration_report_id: UUID
    idempotency_key: str
    source_commit_sha: str = ""
    reason: str = ""
    created_at: datetime | None = None


class EmbeddingActivationResult(BaseModel):
    """Atomic output proving both report and cutover receipt committed."""

    model_config = ConfigDict(frozen=True)

    report: EmbeddingCalibrationReportRecord
    receipt: EmbeddingActivationReceipt


def canonical_dataset_sha256(dataset: EmbeddingCalibrationDataset) -> str:
    payload = dataset.model_dump(mode="json")
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def bind_calibration_report(
    *,
    space_id: UUID,
    source_watermark: datetime,
    result: EmbeddingCalibrationResult,
) -> EmbeddingCalibrationReportDraft:
    payload = {
        "space_id": str(space_id),
        "source_watermark": source_watermark.isoformat(),
        "result": result.model_dump(mode="json"),
    }
    fingerprint = hashlib.sha256(
        json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()
    return EmbeddingCalibrationReportDraft(
        space_id=space_id,
        source_watermark=source_watermark,
        report_fingerprint=fingerprint,
        result=result,
    )


__all__ = [
    "ActivationAction",
    "CalibrationDatasetArtifact",
    "CalibrationScoreDistribution",
    "EmbeddingActivationCommand",
    "EmbeddingActivationReceipt",
    "EmbeddingActivationResult",
    "EmbeddingCalibrationDataset",
    "EmbeddingCalibrationReportDraft",
    "EmbeddingCalibrationReportRecord",
    "EmbeddingCalibrationResult",
    "EmbeddingCalibrationSample",
    "EmbeddingCalibrationScore",
    "EmbeddingCalibrationMeasurement",
    "EmbeddingRollbackCommand",
    "GenerationValidationChecks",
    "GenerationValidationEvidence",
    "ScoreSummary",
    "ValidationState",
    "bind_calibration_report",
    "canonical_dataset_sha256",
]
