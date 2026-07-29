"""Embedding clients, cache, and application lifecycle.

Configuration resolution lives in :mod:`embedding_config`.  This module owns
only transport clients and runtime state.  Clients are cached by a configuration
fingerprint so changing a connection, endpoint, key, headers, model, or declared
dimension cannot accidentally reuse an old client.
"""

from __future__ import annotations

import asyncio
import logging
import math
import time
from dataclasses import dataclass
from collections.abc import Callable
from typing import Literal

import litellm
from langchain_core.embeddings import Embeddings

from app.infra.config import get_settings
from app.infra.llm.embedding_config import (
    ResolvedEmbeddingConfig,
    resolve_embedding_config,
)
from app.infra.llm.embedding_errors import (
    EmbeddingDimensionError,
    EmbeddingErrorCategory,
    classify_embedding_error,
    safe_embedding_error,
)

logger = logging.getLogger(__name__)

EmbeddingProbeErrorCategory = EmbeddingErrorCategory
EmbeddingCompatibilityReason = Literal[
    "compatible",
    "embedding_not_configured",
    "embedding_dimension_unknown",
    "embedding_dimension_mismatch",
]


@dataclass(frozen=True)
class EmbeddingRuntimeProbe:
    """Typed result of a non-fatal embedding runtime probe."""

    probe_ok: bool
    probe_kind: Literal["embedding"] = "embedding"
    embedding_dimensions: int | None = None
    error_category: EmbeddingProbeErrorCategory | None = None
    message: str = ""
    fingerprint: str = ""
    elapsed_ms: float = 0.0


@dataclass(frozen=True)
class EmbeddingDimensionCompatibility:
    """Whether the active embedding output is safe for persistent vectors."""

    compatible: bool
    storage_dimension: int | None
    embedding_dimension: int | None
    reason: EmbeddingCompatibilityReason
    fingerprint: str = ""


@dataclass(frozen=True)
class EmbeddingObservation:
    """One model configuration with its provider-observed output dimension."""

    config: ResolvedEmbeddingConfig
    embeddings: "LiteLLMEmbeddings"
    dimensions: int


class LiteLLMEmbeddings(Embeddings):
    """Async LiteLLM-backed LangChain embedding client."""

    def __init__(self, config: ResolvedEmbeddingConfig):
        self.config = config
        self.model = config.model
        self.api_key = config.api_key
        self.api_base = config.base_url
        self.extra_headers = dict(config.headers)
        self.fingerprint = config.fingerprint

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        raise NotImplementedError(
            "Use aembed_documents(); synchronous embedding blocks async runtimes."
        )

    def embed_query(self, text: str) -> list[float]:
        raise NotImplementedError(
            "Use aembed_query(); synchronous embedding blocks async runtimes."
        )

    async def aembed_documents(self, texts: list[str]) -> list[list[float]]:
        response = await litellm.aembedding(
            model=self.model,
            input=texts,
            api_key=self.api_key,
            api_base=self.api_base,
            extra_headers=self.extra_headers or None,
        )
        vectors = [_coerce_vector(item["embedding"]) for item in response.data]
        if len(vectors) != len(texts):
            raise EmbeddingDimensionError(
                "Embedding provider returned a different number of vectors "
                f"(expected={len(texts)}, actual={len(vectors)})"
            )
        _record_vector_dimensions(self.fingerprint, vectors)
        return vectors

    async def aembed_query(self, text: str) -> list[float]:
        response = await litellm.aembedding(
            model=self.model,
            input=[text],
            api_key=self.api_key,
            api_base=self.api_base,
            extra_headers=self.extra_headers or None,
        )
        if not response.data:
            raise EmbeddingDimensionError("Embedding provider returned no vectors")
        vector = _coerce_vector(response.data[0]["embedding"])
        _record_vector_dimensions(self.fingerprint, [vector])
        return vector


_clients_by_fingerprint: dict[str, LiteLLMEmbeddings] = {}
_configs_by_fingerprint: dict[str, ResolvedEmbeddingConfig] = {}
_observed_dimensions: dict[str, int] = {}
_observation_subscribers: set[Callable[[EmbeddingObservation], None]] = set()
_active_config: ResolvedEmbeddingConfig | None = None
_active_client: LiteLLMEmbeddings | None = None


def initialize_embedding_runtime(model_id: str = "") -> ResolvedEmbeddingConfig | None:
    """Resolve and activate the single startup embedding configuration."""

    global _active_config, _active_client
    config = resolve_embedding_config(model_id)
    _active_config = config
    _active_client = get_embedding_client(config) if config is not None else None
    if config is None:
        logger.warning(
            "No embedding model is active; semantic routing will use keywords "
            "and persistent vector features will remain disabled"
        )
        return None
    logger.info(
        "Embedding runtime configured: source=%s provider=%s model=%s "
        "declared_dimensions=%s fingerprint=%s",
        config.source,
        config.provider,
        config.model,
        config.dimension if config.dimension is not None else "unknown",
        config.fingerprint[:12],
    )
    return config


def init_embedding_model() -> None:
    """Backward-compatible alias for legacy startup integrations."""

    from app.infra.llm.manager import get_model_manager

    manager = get_model_manager()
    if (
        not getattr(manager, "_initialized", False)
        and not get_settings().SYSTEM_DEFAULT_EMBEDDING_MODEL
    ):
        logger.info(
            "Embedding runtime initialization deferred until database model "
            "configuration is available"
        )
        return
    initialize_embedding_runtime()


def get_embedding_client(
    config: ResolvedEmbeddingConfig | None = None,
    *,
    model_id: str = "",
) -> LiteLLMEmbeddings | None:
    """Return one cached client for an explicit resolved configuration."""

    resolved = config
    if resolved is None:
        resolved = resolve_embedding_config(model_id)
    if resolved is None:
        return None
    client = _clients_by_fingerprint.get(resolved.fingerprint)
    if client is None:
        client = LiteLLMEmbeddings(resolved)
        _clients_by_fingerprint[resolved.fingerprint] = client
    _configs_by_fingerprint[resolved.fingerprint] = resolved
    return client


def get_embeddings() -> LiteLLMEmbeddings | None:
    """Return the startup-activated client used by persistent components."""

    return _active_client


def get_configured_embeddings(model_id: str = "") -> LiteLLMEmbeddings | None:
    """Return the current DB-first client for routing and model probes.

    Resolving from the in-memory ModelManager is cheap.  Fingerprint caching
    makes this hot-reload safe without constructing a client per request.
    """

    if model_id:
        return get_embedding_client(model_id=model_id)
    config = resolve_embedding_config()
    if config is None:
        return None
    if (
        _active_config is not None
        and config.fingerprint == _active_config.fingerprint
    ):
        return _active_client
    return get_embedding_client(config)


def get_active_embedding_config() -> ResolvedEmbeddingConfig | None:
    return _active_config


def get_observed_embedding_dimension(
    config: ResolvedEmbeddingConfig | None = None,
) -> int | None:
    resolved = config or _active_config
    if resolved is None:
        return None
    return _observed_dimensions.get(resolved.fingerprint)


def subscribe_embedding_observations(
    callback: Callable[[EmbeddingObservation], None],
) -> Callable[[], None]:
    """Subscribe to first-class dimension observations.

    The returned function removes the subscription.  Callbacks must remain
    non-blocking; persistent rebuilds schedule their own background work.
    """

    _observation_subscribers.add(callback)

    def unsubscribe() -> None:
        _observation_subscribers.discard(callback)

    return unsubscribe


async def probe_embedding_runtime(
    config: ResolvedEmbeddingConfig | None = None,
    *,
    timeout_seconds: float = 1.5,
    text: str = "embedding runtime readiness",
) -> EmbeddingRuntimeProbe:
    """Probe the embedding transport without making startup depend on it."""

    resolved = config or _active_config
    if resolved is None:
        return EmbeddingRuntimeProbe(
            probe_ok=False,
            error_category="provider",
            message="No embedding model is configured",
        )
    client = get_embedding_client(resolved)
    assert client is not None
    started = time.perf_counter()
    try:
        async with asyncio.timeout(timeout_seconds):
            vector = await client.aembed_query(text)
    except TimeoutError:
        return EmbeddingRuntimeProbe(
            probe_ok=False,
            error_category="network",
            message=f"Embedding probe exceeded {timeout_seconds:.1f}s",
            fingerprint=resolved.fingerprint,
            elapsed_ms=(time.perf_counter() - started) * 1000,
        )
    except Exception as exc:
        return EmbeddingRuntimeProbe(
            probe_ok=False,
            error_category=classify_embedding_error(exc),
            message=safe_embedding_error(exc),
            fingerprint=resolved.fingerprint,
            elapsed_ms=(time.perf_counter() - started) * 1000,
        )
    return EmbeddingRuntimeProbe(
        probe_ok=True,
        embedding_dimensions=len(vector),
        fingerprint=resolved.fingerprint,
        elapsed_ms=(time.perf_counter() - started) * 1000,
    )


def assess_persistent_embedding_compatibility(
    config: ResolvedEmbeddingConfig | None = None,
    *,
    storage_dimension: int | None = None,
) -> EmbeddingDimensionCompatibility:
    """Gate persistent vectors on an observed or explicitly declared dimension."""

    resolved = config or _active_config
    if resolved is None:
        return EmbeddingDimensionCompatibility(
            compatible=False,
            storage_dimension=storage_dimension,
            embedding_dimension=None,
            reason="embedding_not_configured",
        )
    actual = _observed_dimensions.get(resolved.fingerprint)
    if actual is None:
        return EmbeddingDimensionCompatibility(
            compatible=False,
            storage_dimension=storage_dimension,
            embedding_dimension=None,
            reason="embedding_dimension_unknown",
            fingerprint=resolved.fingerprint,
        )
    if storage_dimension is not None and actual != storage_dimension:
        return EmbeddingDimensionCompatibility(
            compatible=False,
            storage_dimension=storage_dimension,
            embedding_dimension=actual,
            reason="embedding_dimension_mismatch",
            fingerprint=resolved.fingerprint,
        )
    return EmbeddingDimensionCompatibility(
        compatible=True,
        storage_dimension=storage_dimension or actual,
        embedding_dimension=actual,
        reason="compatible",
        fingerprint=resolved.fingerprint,
    )


def get_persistent_embeddings() -> LiteLLMEmbeddings | None:
    """Return the active client after its real output dimension is observed."""

    compatibility = assess_persistent_embedding_compatibility()
    if not compatibility.compatible:
        return None
    return _active_client


def reset_embedding_runtime() -> None:
    """Clear runtime state for shutdown and isolated verification."""

    global _active_config, _active_client
    _active_config = None
    _active_client = None
    _clients_by_fingerprint.clear()
    _configs_by_fingerprint.clear()
    _observed_dimensions.clear()
    _observation_subscribers.clear()


def _record_vector_dimensions(
    fingerprint: str,
    vectors: list[list[float]],
) -> None:
    dimensions = {len(vector) for vector in vectors}
    if len(dimensions) != 1:
        raise EmbeddingDimensionError(
            f"Embedding provider returned inconsistent dimensions: {sorted(dimensions)}"
        )
    dimension = next(iter(dimensions), 0)
    if dimension <= 0:
        raise EmbeddingDimensionError("Embedding provider returned an empty vector")
    previous = _observed_dimensions.get(fingerprint)
    if previous is not None and previous != dimension:
        logger.warning(
            "Embedding provider changed output dimensions; a new semantic "
            "generation will be requested: fingerprint=%s previous=%d actual=%d",
            fingerprint[:12],
            previous,
            dimension,
        )
    _observed_dimensions[fingerprint] = dimension
    if previous != dimension:
        config = _configs_by_fingerprint.get(fingerprint)
        client = _clients_by_fingerprint.get(fingerprint)
        if config is not None and client is not None:
            observation = EmbeddingObservation(
                config=config,
                embeddings=client,
                dimensions=dimension,
            )
            for callback in tuple(_observation_subscribers):
                try:
                    callback(observation)
                except Exception:
                    logger.exception(
                        "Embedding observation subscriber failed: fingerprint=%s",
                        fingerprint[:12],
                    )


def _coerce_vector(value: object) -> list[float]:
    if not isinstance(value, (list, tuple)):
        raise EmbeddingDimensionError(
            "Embedding provider returned a non-array vector"
        )
    vector = [float(item) for item in value]
    if not vector or any(not math.isfinite(item) for item in vector):
        raise EmbeddingDimensionError(
            "Embedding provider returned an empty or non-finite vector"
        )
    return vector


__all__ = [
    "EmbeddingDimensionCompatibility",
    "EmbeddingObservation",
    "EmbeddingProbeErrorCategory",
    "EmbeddingRuntimeProbe",
    "LiteLLMEmbeddings",
    "assess_persistent_embedding_compatibility",
    "get_active_embedding_config",
    "get_configured_embeddings",
    "get_embedding_client",
    "get_embeddings",
    "get_observed_embedding_dimension",
    "get_persistent_embeddings",
    "init_embedding_model",
    "initialize_embedding_runtime",
    "probe_embedding_runtime",
    "reset_embedding_runtime",
    "subscribe_embedding_observations",
]
