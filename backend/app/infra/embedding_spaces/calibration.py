"""Pure threshold selection and quality-gate evaluation."""

from __future__ import annotations

from collections.abc import Iterable
from statistics import fmean

from app.infra.embedding_spaces.calibration_contracts import (
    CalibrationDatasetArtifact,
    CalibrationScoreDistribution,
    EmbeddingCalibrationResult,
    EmbeddingCalibrationScore,
    GenerationValidationEvidence,
    ScoreSummary,
)


def calibrate_embedding_generation(
    *,
    artifact: CalibrationDatasetArtifact,
    scores: Iterable[EmbeddingCalibrationScore],
    evidence: GenerationValidationEvidence,
) -> EmbeddingCalibrationResult:
    """Choose a deterministic threshold and evaluate every admission gate."""

    dataset = artifact.dataset
    score_items = tuple(scores)
    score_map: dict[str, float] = {}
    duplicate_ids: set[str] = set()
    for item in score_items:
        if item.sample_id in score_map:
            duplicate_ids.add(item.sample_id)
        score_map[item.sample_id] = item.score

    expected_ids = {sample.sample_id for sample in dataset.samples}
    coverage_matches = (
        not duplicate_ids
        and set(score_map) == expected_ids
        and len(score_items) == len(dataset.samples)
    )
    labeled_scores = [
        (sample.relevant, score_map[sample.sample_id])
        for sample in dataset.samples
        if sample.sample_id in score_map
    ]
    threshold, precision, recall, f1 = _best_threshold(labeled_scores)
    positives = [score for relevant, score in labeled_scores if relevant]
    negatives = [score for relevant, score in labeled_scores if not relevant]
    checks = evidence.checks()

    failures: list[str] = []
    if len(dataset.samples) < dataset.minimum_samples:
        failures.append("insufficient_samples")
    if not coverage_matches:
        failures.append("score_coverage_mismatch")
    if checks.dimensions != "passed":
        failures.append("dimensions_failed")
    if checks.row_count != "passed":
        failures.append("row_count_mismatch")
    if evidence.purpose == "memory":
        if checks.active_fact_filter != "passed":
            failures.append("active_fact_filter_failed")
        if checks.tenant_isolation != "passed":
            failures.append("tenant_isolation_failed")
    if checks.single_generation_query != "passed":
        failures.append("single_generation_query_failed")
    if precision < dataset.minimum_precision:
        failures.append("precision_below_gate")
    if recall < dataset.minimum_recall:
        failures.append("recall_below_gate")

    return EmbeddingCalibrationResult(
        dataset_version=dataset.dataset_version,
        dataset_sha256=artifact.sha256,
        threshold=threshold,
        sample_count=len(dataset.samples),
        positive_count=sum(sample.relevant for sample in dataset.samples),
        negative_count=sum(not sample.relevant for sample in dataset.samples),
        precision_score=precision,
        recall_score=recall,
        f1_score=f1,
        score_distribution=CalibrationScoreDistribution(
            positive=_summarize(positives),
            negative=_summarize(negatives),
        ),
        validation_checks=checks,
        status="failed" if failures else "passed",
        failure_codes=tuple(failures),
    )


def _best_threshold(
    labeled_scores: list[tuple[bool, float]],
) -> tuple[float, float, float, float]:
    if not labeled_scores:
        return 1.0, 0.0, 0.0, 0.0

    thresholds = sorted({score for _, score in labeled_scores})
    best: tuple[float, float, float, float] | None = None
    for threshold in thresholds:
        true_positive = sum(
            relevant and score >= threshold for relevant, score in labeled_scores
        )
        false_positive = sum(
            not relevant and score >= threshold for relevant, score in labeled_scores
        )
        false_negative = sum(
            relevant and score < threshold for relevant, score in labeled_scores
        )
        precision = _ratio(true_positive, true_positive + false_positive)
        recall = _ratio(true_positive, true_positive + false_negative)
        f1 = _ratio(2.0 * precision * recall, precision + recall)
        candidate = (f1, precision, recall, threshold)
        if best is None or candidate > best:
            best = candidate

    assert best is not None
    f1, precision, recall, threshold = best
    return threshold, precision, recall, f1


def _ratio(numerator: float, denominator: float) -> float:
    return numerator / denominator if denominator else 0.0


def _summarize(values: list[float]) -> ScoreSummary:
    if not values:
        return ScoreSummary(count=0, minimum=0.0, maximum=0.0, mean=0.0)
    return ScoreSummary(
        count=len(values),
        minimum=min(values),
        maximum=max(values),
        mean=fmean(values),
    )


__all__ = ["calibrate_embedding_generation"]
