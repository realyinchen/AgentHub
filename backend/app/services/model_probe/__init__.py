from __future__ import annotations

from typing import Protocol

from app.services.model_probe.chat import ChatProbe
from app.services.model_probe.contracts import ProbeConfig, ProbeOutcome
from app.services.model_probe.embedding import EmbeddingProbe


class ModelProbe(Protocol):
    async def run(self, config: ProbeConfig) -> ProbeOutcome: ...


def get_model_probe(model_type: str) -> ModelProbe:
    """Select a probe by model modality without invoking it."""

    if model_type == "embedding":
        return EmbeddingProbe()
    if model_type in {"llm", "vlm"}:
        return ChatProbe()
    raise ValueError(f"Unsupported model type: {model_type}")


__all__ = [
    "ModelProbe",
    "ProbeConfig",
    "ProbeOutcome",
    "get_model_probe",
]
