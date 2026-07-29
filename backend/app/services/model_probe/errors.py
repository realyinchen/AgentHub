from __future__ import annotations

from app.infra.llm.embedding_errors import (
    EmbeddingDimensionError,
    classify_embedding_error,
    safe_embedding_error,
)
from app.services.model_probe.contracts import ProbeErrorCategory


def classify_probe_error(exc: Exception) -> ProbeErrorCategory:
    """Map provider-specific exceptions to a stable, transport-neutral category."""

    return classify_embedding_error(exc)


def safe_probe_error(exc: Exception, *, limit: int = 1000) -> str:
    return safe_embedding_error(exc, limit=limit)


__all__ = [
    "EmbeddingDimensionError",
    "classify_probe_error",
    "safe_probe_error",
]
