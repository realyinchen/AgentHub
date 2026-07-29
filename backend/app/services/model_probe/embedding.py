from __future__ import annotations

import asyncio
import math
from collections.abc import Callable, Sequence
from numbers import Real
from typing import Protocol

from app.infra.llm.embedding import get_embedding_client
from app.services.model_probe.contracts import ProbeConfig, ProbeOutcome
from app.services.model_probe.errors import (
    EmbeddingDimensionError,
    classify_probe_error,
    safe_probe_error,
)


PROBE_TEXTS = (
    "AgentHub embedding capability probe.",
    "AgentHub embedding dimension verification.",
)


class EmbeddingClient(Protocol):
    async def aembed_documents(self, texts: list[str]) -> list[list[float]]: ...


EmbeddingClientFactory = Callable[[ProbeConfig], EmbeddingClient]


class EmbeddingProbe:
    """Probe embedding generation and validate vector shape and values."""

    probe_kind = "embedding"

    def __init__(
        self,
        client_factory: EmbeddingClientFactory | None = None,
    ) -> None:
        self._client_factory = client_factory or _build_embedding_client

    async def run(self, config: ProbeConfig) -> ProbeOutcome:
        outcome = ProbeOutcome(probe_kind=self.probe_kind, probe_ok=False)
        try:
            client = self._client_factory(config)
            vectors = await asyncio.wait_for(
                client.aembed_documents(list(PROBE_TEXTS)),
                timeout=config.timeout_seconds,
            )
            dimensions = _validate_vectors(
                vectors,
                expected_count=len(PROBE_TEXTS),
                expected_dimensions=config.expected_embedding_dimensions,
            )
        except Exception as exc:
            outcome.error_category = classify_probe_error(exc)
            outcome.error_type = (
                "invalid_embedding_dimensions"
                if outcome.error_category == "dimension"
                else "embedding_request_failed"
            )
            outcome.last_error = safe_probe_error(exc)
            return outcome

        outcome.probe_ok = True
        outcome.embedding_dimensions = dimensions
        outcome.summary.update(
            {
                "embedding_vector_count": len(vectors),
                "embedding_dimensions": dimensions,
            }
        )
        return outcome


def _build_embedding_client(config: ProbeConfig) -> EmbeddingClient:
    if config.embedding_config is None:
        raise ValueError("Embedding runtime configuration could not be resolved.")
    client = get_embedding_client(config.embedding_config)
    if client is None:
        raise ValueError("Embedding client could not be created.")
    return client


def _validate_vectors(
    vectors: Sequence[Sequence[Real]],
    *,
    expected_count: int,
    expected_dimensions: int | None,
) -> int:
    if (
        not isinstance(vectors, Sequence)
        or isinstance(vectors, (str, bytes))
        or len(vectors) != expected_count
    ):
        raise EmbeddingDimensionError(
            f"Expected {expected_count} embedding vectors, got "
            f"{len(vectors) if hasattr(vectors, '__len__') else 'invalid'}."
        )

    dimensions: set[int] = set()
    for vector in vectors:
        if isinstance(vector, (str, bytes)) or not vector:
            raise EmbeddingDimensionError("Embedding response contained an empty vector.")
        dimensions.add(len(vector))
        if any(
            isinstance(value, bool)
            or not isinstance(value, Real)
            or not math.isfinite(float(value))
            for value in vector
        ):
            raise EmbeddingDimensionError(
                "Embedding response contained a non-finite or non-numeric value."
            )

    if len(dimensions) != 1:
        raise EmbeddingDimensionError(
            f"Embedding vectors have inconsistent dimensions: {sorted(dimensions)}."
        )

    dimensions_value = dimensions.pop()
    if (
        expected_dimensions is not None
        and dimensions_value != expected_dimensions
    ):
        raise EmbeddingDimensionError(
            "Embedding dimension mismatch: "
            f"expected {expected_dimensions}, got {dimensions_value}."
        )
    return dimensions_value


__all__ = ["EmbeddingProbe"]
