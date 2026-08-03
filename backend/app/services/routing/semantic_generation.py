"""Build immutable, generation-calibrated routing prototype indexes."""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Callable
from dataclasses import dataclass

from app.infra.embedding_spaces.calibration import (
    calibrate_embedding_generation,
)
from app.infra.embedding_spaces.calibration_contracts import (
    EmbeddingCalibrationResult,
    EmbeddingCalibrationScore,
    GenerationValidationEvidence,
)
from app.infra.embedding_spaces.calibration_dataset import (
    load_default_calibration_dataset,
)
from app.infra.embedding_spaces.similarity import cosine_similarity
from app.services.routing.semantic_prototypes import PROTOTYPES


@dataclass(frozen=True)
class RoutingPrototypeVector:
    phrase: str
    vector: tuple[float, ...]


@dataclass(frozen=True)
class RoutingSemanticGeneration:
    """A fully built routing index; partial generations are never published."""

    generation_fingerprint: str
    model_fingerprint: str
    dimensions: int
    threshold: float
    dataset_version: str
    dataset_sha256: str
    calibration: EmbeddingCalibrationResult | None
    prototype_vectors: tuple[RoutingPrototypeVector, ...]

    @property
    def calibrated(self) -> bool:
        return self.calibration is not None and self.calibration.status == "passed"

    def vectors_by_phrase(self) -> dict[str, tuple[float, ...]]:
        return {item.phrase: item.vector for item in self.prototype_vectors}


class RoutingSemanticCalibrationError(RuntimeError):
    def __init__(self, result: EmbeddingCalibrationResult) -> None:
        self.result = result
        super().__init__(
            "routing_semantic_calibration_failed:" + ",".join(result.failure_codes)
        )


class RoutingSemanticGenerationBuilder:
    """Own the provider call needed to build a complete off-side generation."""

    async def build(
        self,
        *,
        embeddings: object,
        model_fingerprint: str,
        model_fingerprint_for_dimensions: Callable[[int], str] | None,
        expected_dimensions: int | None,
        calibrated: bool,
        compatibility_threshold: float,
    ) -> RoutingSemanticGeneration:
        prototype_phrases = tuple(
            phrase for prototype in PROTOTYPES for phrase in prototype.phrases
        )
        artifact = load_default_calibration_dataset() if calibrated else None
        calibration_texts = (
            tuple(
                text
                for sample in artifact.dataset.samples
                for text in (sample.query, sample.anchor)
            )
            if artifact is not None
            else ()
        )
        texts = tuple(dict.fromkeys((*prototype_phrases, *calibration_texts)))
        vectors = await embeddings.aembed_documents(list(texts))  # type: ignore[attr-defined]
        if len(vectors) != len(texts):
            raise ValueError("Routing semantic generation vector count mismatch")
        dimensions = {len(vector) for vector in vectors}
        if len(dimensions) != 1:
            raise ValueError(
                "Routing semantic generation returned inconsistent dimensions"
            )
        observed_dimensions = next(iter(dimensions), 0)
        if observed_dimensions <= 0:
            raise ValueError("Routing semantic generation returned empty vectors")
        if not all(
            vector and all(math.isfinite(value) for value in vector)
            for vector in vectors
        ):
            raise ValueError("Routing semantic generation returned non-finite vectors")
        if (
            expected_dimensions is not None
            and observed_dimensions != expected_dimensions
        ):
            raise ValueError(
                "Routing semantic generation dimension changed during build"
            )
        resolved_model_fingerprint = (
            model_fingerprint_for_dimensions(observed_dimensions)
            if model_fingerprint_for_dimensions is not None
            else model_fingerprint
        )

        vector_map = dict(zip(texts, vectors, strict=True))
        calibration_result: EmbeddingCalibrationResult | None = None
        threshold = compatibility_threshold
        dataset_version = ""
        dataset_sha256 = ""
        if artifact is not None:
            scores = [
                EmbeddingCalibrationScore(
                    sample_id=sample.sample_id,
                    score=cosine_similarity(
                        vector_map[sample.query],
                        vector_map[sample.anchor],
                    ),
                )
                for sample in artifact.dataset.samples
            ]
            calibration_result = calibrate_embedding_generation(
                artifact=artifact,
                scores=scores,
                evidence=GenerationValidationEvidence(
                    purpose="routing",
                    expected_dimensions=observed_dimensions,
                    observed_dimensions=observed_dimensions,
                    source_count=len(prototype_phrases),
                    embedded_count=len(prototype_phrases),
                    stored_count=len(prototype_phrases),
                    active_fact_filter="not_applicable",
                    tenant_isolation="not_applicable",
                    single_generation_query="passed",
                ),
            )
            if calibration_result.status != "passed":
                raise RoutingSemanticCalibrationError(calibration_result)
            threshold = calibration_result.threshold
            dataset_version = calibration_result.dataset_version
            dataset_sha256 = calibration_result.dataset_sha256

        catalog_fingerprint = hashlib.sha256(
            json.dumps(
                [
                    {
                        "intent": prototype.intent,
                        "domain": prototype.domain,
                        "phrases": prototype.phrases,
                    }
                    for prototype in PROTOTYPES
                ],
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            ).encode("utf-8")
        ).hexdigest()
        generation_fingerprint = hashlib.sha256(
            json.dumps(
                {
                    "model_fingerprint": resolved_model_fingerprint,
                    "dimensions": observed_dimensions,
                    "catalog_fingerprint": catalog_fingerprint,
                    "dataset_sha256": dataset_sha256,
                },
                separators=(",", ":"),
                sort_keys=True,
            ).encode("utf-8")
        ).hexdigest()
        return RoutingSemanticGeneration(
            generation_fingerprint=generation_fingerprint,
            model_fingerprint=resolved_model_fingerprint,
            dimensions=observed_dimensions,
            threshold=threshold,
            dataset_version=dataset_version,
            dataset_sha256=dataset_sha256,
            calibration=calibration_result,
            prototype_vectors=tuple(
                RoutingPrototypeVector(
                    phrase=phrase,
                    vector=tuple(float(value) for value in vector_map[phrase]),
                )
                for phrase in prototype_phrases
            ),
        )


__all__ = [
    "RoutingPrototypeVector",
    "RoutingSemanticCalibrationError",
    "RoutingSemanticGeneration",
    "RoutingSemanticGenerationBuilder",
]
