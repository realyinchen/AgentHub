from __future__ import annotations

from datetime import date, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.services.agent_core.shadow_gate_contracts import (
    ShadowGateDataset,
    ShadowGateReport,
)


MINIMUM_SHADOW_TURNS = 500
MINIMUM_CONSECUTIVE_NATURAL_DAYS = 3


class ShadowGateEvaluator:
    """Pure fixed-threshold evaluation of a versioned Shadow dataset."""

    def evaluate(
        self,
        dataset: ShadowGateDataset,
    ) -> ShadowGateReport:
        failed: list[str] = []
        blocked: list[str] = []
        error_keys: set[str] = set()
        blocked_keys: set[str] = set()
        observations = list(dataset.observations)
        keys = [item.observation_key for item in observations]
        unique_keys = set(keys)
        if len(unique_keys) != len(keys):
            failed.append("duplicate_observation_keys")

        source_mismatches = [
            item.observation_key
            for item in observations
            if item.source_commit_sha != dataset.commit_sha
        ]
        if source_mismatches:
            failed.append("source_commit_mixed")
            error_keys.update(source_mismatches)
        controller_mismatches = [
            item.observation_key
            for item in observations
            if item.controller_fingerprint
            != dataset.controller_fingerprint
        ]
        if controller_mismatches:
            failed.append("controller_fingerprint_mixed")
            error_keys.update(controller_mismatches)
        configuration_mismatches = [
            item.observation_key
            for item in observations
            if item.configuration_fingerprint
            != dataset.configuration_fingerprint
        ]
        if configuration_mismatches:
            failed.append("configuration_fingerprint_mixed")
            error_keys.update(configuration_mismatches)

        coverage = dataset.coverage
        if coverage.observed != len(unique_keys):
            failed.append("coverage_observation_count_mismatch")
        if coverage.pending_within_grace:
            blocked.append("enrollment_delivery_within_grace")
        if coverage.missing_after_grace:
            failed.append("enrollment_delivery_missing")
        if dataset.collected_at < dataset.window_ended_at:
            blocked.append("collection_window_open")

        difference_count = 0
        reviewed_difference_count = 0
        audit_receipt_count = 0
        for item in observations:
            if item.controller_status != "shadow_valid":
                failed.append("non_valid_shadow_outcomes")
                error_keys.add(item.observation_key)
            if item.journal_terminal_count != 1:
                blocked.append("journal_terminal_coverage_incomplete")
                blocked_keys.add(item.observation_key)
            if not item.journal_watermark_match:
                failed.append("journal_watermark_mismatch")
                error_keys.add(item.observation_key)
            if item.audit_receipt_count:
                audit_receipt_count += item.audit_receipt_count
                error_keys.add(item.observation_key)
            if (
                item.system_field_violation_count
                or item.publication_violation_count
                or item.memory_high_risk_event_count
            ):
                error_keys.add(item.observation_key)
            if item.system_field_violation_count:
                failed.append("system_field_violations_nonzero")
            if item.publication_violation_count:
                failed.append("publication_violations_nonzero")
            if item.memory_high_risk_event_count:
                failed.append("memory_high_risk_events_nonzero")

            if item.difference_kind is None:
                continue
            difference_count += 1
            if item.review is None:
                blocked.append("unreviewed_differences_nonzero")
                blocked_keys.add(item.observation_key)
                continue
            reviewed_difference_count += 1
            if (
                item.review.difference_fingerprint
                != item.difference_fingerprint
            ):
                failed.append("stale_difference_reviews_nonzero")
                error_keys.add(item.observation_key)
            if not item.review.explained:
                if item.review.severity in {"P0", "P1"}:
                    failed.append("unexplained_p0_p1_differences_nonzero")
                    error_keys.add(item.observation_key)
                else:
                    blocked.append("unexplained_differences_nonzero")
                    blocked_keys.add(item.observation_key)

        if audit_receipt_count:
            failed.append("shadow_audit_receipts_nonzero")
        sample_count = len(unique_keys)
        if sample_count < MINIMUM_SHADOW_TURNS:
            blocked.append("sample_count_below_500")

        natural_dates = _natural_dates(
            observations,
            timezone_name=dataset.timezone,
        )
        consecutive_days = _max_consecutive_days(natural_dates)
        if consecutive_days < MINIMUM_CONSECUTIVE_NATURAL_DAYS:
            blocked.append("consecutive_natural_days_below_3")

        failed = _deduplicate(failed)
        blocked = _deduplicate(blocked)
        latencies = [item.latency_ms for item in observations]
        status = (
            "failed"
            if failed
            else "blocked"
            if blocked
            else "passed"
        )
        return ShadowGateReport(
            status=status,
            commit_sha=dataset.commit_sha,
            controller_fingerprint=dataset.controller_fingerprint,
            configuration_fingerprint=dataset.configuration_fingerprint,
            prompt_version=dataset.prompt_version,
            sample_count=sample_count,
            natural_day_count=len(natural_dates),
            max_consecutive_natural_days=consecutive_days,
            difference_count=difference_count,
            reviewed_difference_count=reviewed_difference_count,
            audit_receipt_count=audit_receipt_count,
            pending_within_grace=coverage.pending_within_grace,
            missing_after_grace=coverage.missing_after_grace,
            latency_p50_ms=_nearest_rank(latencies, 0.50),
            latency_p95_ms=_nearest_rank(latencies, 0.95),
            review_artifact_hash=dataset.review_artifact_hash,
            reasons=[*failed, *blocked],
            error_observation_keys=sorted(error_keys),
            blocked_observation_keys=sorted(blocked_keys),
        )


def _natural_dates(
    observations,
    *,
    timezone_name: str,
) -> set[date]:
    try:
        selected_timezone = ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError as exc:
        raise ValueError(
            f"unknown Shadow report timezone: {timezone_name}"
        ) from exc
    dates: set[date] = set()
    for observation in observations:
        timestamp = observation.created_at
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=timezone.utc)
        dates.add(timestamp.astimezone(selected_timezone).date())
    return dates


def _max_consecutive_days(values: set[date]) -> int:
    if not values:
        return 0
    longest = 1
    current = 1
    ordered = sorted(values)
    for previous, candidate in zip(ordered, ordered[1:]):
        if candidate - previous == timedelta(days=1):
            current += 1
            longest = max(longest, current)
        else:
            current = 1
    return longest


def _deduplicate(values: list[str]) -> list[str]:
    return list(dict.fromkeys(values))


def _nearest_rank(values: list[int], percentile: float) -> int:
    if not values:
        return 0
    ordered = sorted(values)
    index = max(
        0,
        min(
            len(ordered) - 1,
            int(len(ordered) * percentile + 0.999999) - 1,
        ),
    )
    return ordered[index]


__all__ = [
    "MINIMUM_CONSECUTIVE_NATURAL_DAYS",
    "MINIMUM_SHADOW_TURNS",
    "ShadowGateEvaluator",
]
