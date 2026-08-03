"""Run one calibration dataset against one embedding model."""

from __future__ import annotations

import math

from langchain_core.embeddings import Embeddings

from app.infra.embedding_spaces.calibration import (
    calibrate_embedding_generation,
)
from app.infra.embedding_spaces.calibration_contracts import (
    CalibrationDatasetArtifact,
    EmbeddingCalibrationMeasurement,
    EmbeddingCalibrationResult,
    EmbeddingCalibrationScore,
    GenerationValidationEvidence,
)
from app.infra.embedding_spaces.similarity import cosine_similarity


class EmbeddingCalibrationRunner:
    """Own model calls for calibration; persistence and activation stay elsewhere."""

    async def run(
        self,
        *,
        embeddings: Embeddings,
        artifact: CalibrationDatasetArtifact,
        evidence: GenerationValidationEvidence,
    ) -> EmbeddingCalibrationResult:
        measurement = await self.measure(
            embeddings=embeddings,
            artifact=artifact,
        )
        measured_evidence = evidence.model_copy(
            update={"observed_dimensions": measurement.observed_dimensions}
        )
        return calibrate_embedding_generation(
            artifact=artifact,
            scores=measurement.scores,
            evidence=measured_evidence,
        )

    async def measure(
        self,
        *,
        embeddings: Embeddings,
        artifact: CalibrationDatasetArtifact,
    ) -> EmbeddingCalibrationMeasurement:
        """Call the provider without holding a generation cutover lock."""

        texts = tuple(
            dict.fromkeys(
                text
                for sample in artifact.dataset.samples
                for text in (sample.query, sample.anchor)
            )
        )
        vectors = await embeddings.aembed_documents(list(texts))
        vector_map = dict(zip(texts, vectors, strict=True))
        dimensions = {len(vector) for vector in vectors}
        vectors_are_finite = all(
            vector and all(math.isfinite(value) for value in vector)
            for vector in vectors
        )
        observed_dimensions = next(iter(dimensions), 0) if len(dimensions) == 1 else 0
        scores: list[EmbeddingCalibrationScore] = []
        if vectors_are_finite and observed_dimensions > 0:
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
        return EmbeddingCalibrationMeasurement(
            observed_dimensions=observed_dimensions,
            scores=tuple(scores),
        )


__all__ = ["EmbeddingCalibrationRunner"]
