"""Load and fingerprint versioned embedding calibration datasets."""

from __future__ import annotations

import json
from pathlib import Path

from app.infra.embedding_spaces.calibration_contracts import (
    CalibrationDatasetArtifact,
    EmbeddingCalibrationDataset,
    canonical_dataset_sha256,
)

DEFAULT_CALIBRATION_DATASET = (
    Path(__file__).resolve().parents[3] / "evals" / "embedding_calibration_v1.json"
)


def load_calibration_dataset(path: Path) -> CalibrationDatasetArtifact:
    payload = json.loads(path.read_text(encoding="utf-8"))
    dataset = EmbeddingCalibrationDataset.model_validate(payload)
    return CalibrationDatasetArtifact(
        dataset=dataset,
        sha256=canonical_dataset_sha256(dataset),
    )


def load_default_calibration_dataset() -> CalibrationDatasetArtifact:
    return load_calibration_dataset(DEFAULT_CALIBRATION_DATASET)


__all__ = [
    "DEFAULT_CALIBRATION_DATASET",
    "load_calibration_dataset",
    "load_default_calibration_dataset",
]
