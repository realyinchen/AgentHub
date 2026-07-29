"""Project non-executable recall candidates into observable evidence."""

from __future__ import annotations

from app.services.routing.contracts import IntentCandidate
from app.services.routing.interaction_contracts import RecallBatch, RoutingEvidence


def merge_candidates(candidates: list[IntentCandidate]) -> list[IntentCandidate]:
    merged: dict[str, IntentCandidate] = {}
    for candidate in candidates:
        current = merged.get(candidate.intent)
        if current is None or candidate.confidence > current.confidence:
            if current is not None:
                candidate = candidate.model_copy(
                    update={"evidence": [*current.evidence, *candidate.evidence]}
                )
            merged[candidate.intent] = candidate
        else:
            merged[candidate.intent] = current.model_copy(
                update={"evidence": [*current.evidence, *candidate.evidence]}
            )
    return sorted(merged.values(), key=lambda item: item.confidence, reverse=True)


def recall_batch(
    *,
    provider: str,
    source: str,
    candidates: list[IntentCandidate],
    latency_ms: float,
    model_key: str | None = None,
) -> RecallBatch:
    evidence = [candidate_evidence(item) for item in candidates]
    return RecallBatch(
        provider=provider,
        source=source,  # type: ignore[arg-type]
        provider_status="matched" if evidence else "no_match",
        evidence=evidence,
        model_key=model_key,
        latency_ms=max(0.0, latency_ms),
    )


def candidate_evidence(candidate: IntentCandidate) -> RoutingEvidence:
    raw_score = candidate.confidence
    for item in candidate.evidence:
        if ":" not in item:
            continue
        key, raw = item.rsplit(":", 1)
        if key in {"lexical_score", "cosine_similarity"}:
            try:
                raw_score = float(raw)
            except ValueError:
                pass
    return RoutingEvidence(
        intent=candidate.intent,
        source=candidate.source,  # type: ignore[arg-type]
        raw_score=max(0.0, min(1.0, raw_score)),
        calibrated_confidence=candidate.confidence,
        matched_span=next(
            (
                item.split(":", 1)[1]
                for item in candidate.evidence
                if item.startswith("prototype:")
            ),
            "",
        ),
        reasons=list(candidate.evidence),
        domain=candidate.domain,
    )
