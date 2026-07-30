from __future__ import annotations

import hashlib
import json
from pathlib import Path

from app.services.agent_core.controller_golden_contracts import (
    ControllerGoldenDataset,
    LoadedControllerGoldenDataset,
)


class ControllerGoldenDatasetLoader:
    """Load one immutable synthetic Controller quality dataset."""

    def load(self, path: str | Path) -> LoadedControllerGoldenDataset:
        raw = Path(path).read_bytes()
        return LoadedControllerGoldenDataset(
            dataset=ControllerGoldenDataset.model_validate(
                json.loads(raw.decode("utf-8"))
            ),
            sha256=hashlib.sha256(raw).hexdigest(),
        )


__all__ = ["ControllerGoldenDatasetLoader"]
