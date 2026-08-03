"""Remote-embedding prototype index and bounded vector recall."""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass

from app.infra.embedding_spaces.contracts import build_embedding_space_spec
from app.infra.embedding_spaces.similarity import cosine_similarity
from app.infra.config import get_settings
from app.infra.llm.embedding import get_configured_embeddings
from app.infra.llm.embedding_config import ResolvedEmbeddingConfig
from app.infra.llm.embedding_errors import (
    EmbeddingErrorCategory,
    classify_embedding_error,
    safe_embedding_error,
)
from app.infra.llm.manager import get_model_manager
from app.services.routing.config import (
    LEGACY_VECTOR_DIAGNOSTIC_THRESHOLD,
    SEMANTIC_WARMUP_TIMEOUT_SECONDS,
    VECTOR_REQUEST_TIMEOUT_SECONDS,
)
from app.services.routing.contracts import IntentCandidate
from app.services.routing.interaction_contracts import RecallBatch
from app.services.routing.recall_projection import recall_batch
from app.services.routing.semantic_generation import (
    RoutingSemanticGeneration,
    RoutingSemanticGenerationBuilder,
)
from app.services.routing.semantic_prototypes import PROTOTYPES


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SemanticWarmupResult:
    ready: bool
    fingerprint: str = ""
    dimensions: int | None = None
    error_category: EmbeddingErrorCategory | None = None
    message: str = ""
    elapsed_ms: float = 0.0

    def __bool__(self) -> bool:
        return self.ready


class VectorPrototypeRecall:
    """Own the vector index and embedding-provider lifecycle only."""

    def __init__(self, *, calibration_required: bool | None = None) -> None:
        self._active_generation: RoutingSemanticGeneration | None = None
        self._previous_generation: RoutingSemanticGeneration | None = None
        self._builder = RoutingSemanticGenerationBuilder()
        self._calibration_required = calibration_required
        self._lock = asyncio.Lock()
        self.last_batch = RecallBatch(
            provider="routing_vector",
            source="vector",
            provider_status="unavailable",
            degraded_reason="not_attempted",
        )
        self.last_warmup_result = SemanticWarmupResult(
            ready=False,
            message="not_started",
        )

    @property
    def active_generation(self) -> RoutingSemanticGeneration | None:
        return self._active_generation

    @property
    def previous_generation(self) -> RoutingSemanticGeneration | None:
        return self._previous_generation

    @property
    def prototype_vectors(self) -> dict[str, list[float]]:
        generation = self._active_generation
        if generation is None:
            return {}
        return {
            phrase: list(vector)
            for phrase, vector in generation.vectors_by_phrase().items()
        }

    @property
    def model_key(self) -> str:
        generation = self._active_generation
        return generation.model_fingerprint if generation is not None else ""

    async def recall(self, text: str) -> list[IntentCandidate]:
        started = time.perf_counter()
        manager = get_model_manager()
        if not getattr(manager, "_initialized", False):
            self.last_batch = _unavailable_batch(
                started,
                "model_manager_not_initialized",
            )
            return []
        embeddings = get_configured_embeddings()
        if embeddings is None:
            self.last_batch = _unavailable_batch(
                started,
                "embedding_model_not_configured",
            )
            return []
        model_key = embedding_fingerprint(embeddings)
        try:
            async with asyncio.timeout(VECTOR_REQUEST_TIMEOUT_SECONDS):
                query_vector = await embeddings.aembed_query(text)
                model_key = embedding_fingerprint(
                    embeddings,
                    dimensions=len(query_vector),
                )
                await self.ensure_index(embeddings, model_key)
        except TimeoutError:
            reason = (
                f"vector_request_timeout_after_{VECTOR_REQUEST_TIMEOUT_SECONDS:.1f}s"
            )
            logger.warning("Routing vector recall degraded: %s", reason)
            self.last_batch = RecallBatch(
                provider="routing_vector",
                source="vector",
                provider_status="degraded",
                model_key=model_key or None,
                latency_ms=_elapsed_ms(started),
                degraded_reason=reason,
            )
            return []
        except Exception as exc:
            category = classify_embedding_error(exc)
            reason = f"{category}:{safe_embedding_error(exc, limit=160)}"
            logger.warning(
                "Routing vector recall failed open for fingerprint=%s: %s",
                model_key[:12],
                reason,
            )
            self.last_batch = RecallBatch(
                provider="routing_vector",
                source="vector",
                provider_status="failed",
                model_key=model_key or None,
                latency_ms=_elapsed_ms(started),
                degraded_reason=reason,
            )
            return []

        candidates = self._rank(query_vector)
        self.last_batch = recall_batch(
            provider="routing_vector",
            source="vector",
            candidates=candidates,
            model_key=model_key or None,
            latency_ms=_elapsed_ms(started),
        )
        return candidates

    async def warm(self) -> SemanticWarmupResult:
        started = time.perf_counter()
        manager = get_model_manager()
        if not getattr(manager, "_initialized", False):
            return self._warmup_failure(
                started,
                "provider",
                "model_manager_not_ready",
            )
        embeddings = get_configured_embeddings()
        if embeddings is None:
            return self._warmup_failure(
                started,
                "provider",
                "embedding_not_configured",
            )
        model_key = ""
        try:
            async with asyncio.timeout(SEMANTIC_WARMUP_TIMEOUT_SECONDS):
                await self.ensure_index(embeddings, model_key)
        except Exception as exc:
            return self._warmup_failure(
                started,
                classify_embedding_error(exc),
                safe_embedding_error(exc),
                fingerprint=model_key or embedding_fingerprint(embeddings),
            )
        generation = self._active_generation
        model_key = self.model_key
        result = SemanticWarmupResult(
            ready=generation is not None,
            fingerprint=model_key,
            dimensions=generation.dimensions if generation is not None else None,
            elapsed_ms=_elapsed_ms(started),
        )
        self.last_warmup_result = result
        logger.info(
            "Routing semantic index ready: fingerprint=%s prototypes=%d "
            "dimensions=%d elapsed_ms=%.1f",
            model_key[:12],
            len(generation.prototype_vectors) if generation is not None else 0,
            generation.dimensions if generation is not None else 0,
            result.elapsed_ms,
        )
        return result

    async def ensure_index(self, embeddings: object, model_key: str) -> None:
        active = self._active_generation
        if active is not None:
            resolved_current_key = model_key or embedding_fingerprint(
                embeddings,
                dimensions=active.dimensions,
            )
            if active.model_fingerprint == resolved_current_key:
                return
        async with self._lock:
            active = self._active_generation
            if active is not None:
                resolved_current_key = model_key or embedding_fingerprint(
                    embeddings,
                    dimensions=active.dimensions,
                )
                if active.model_fingerprint == resolved_current_key:
                    return
            calibration_required = (
                get_settings().EMBEDDING_GENERATION_GATES_V1
                if self._calibration_required is None
                else self._calibration_required
            )
            generation = await self._builder.build(
                embeddings=embeddings,
                model_fingerprint=model_key or embedding_fingerprint(embeddings),
                model_fingerprint_for_dimensions=(
                    None
                    if model_key
                    else lambda dimensions: embedding_fingerprint(
                        embeddings,
                        dimensions=dimensions,
                    )
                ),
                expected_dimensions=None,
                calibrated=calibration_required,
                compatibility_threshold=LEGACY_VECTOR_DIAGNOSTIC_THRESHOLD,
            )
            self._previous_generation = self._active_generation
            self._active_generation = generation

    def _rank(self, query_vector: list[float]) -> list[IntentCandidate]:
        generation = self._active_generation
        if generation is None or len(query_vector) != generation.dimensions:
            return []
        prototype_vectors = generation.vectors_by_phrase()
        candidates: list[IntentCandidate] = []
        for prototype in PROTOTYPES:
            best_score = 0.0
            best_phrase = ""
            for phrase in prototype.phrases:
                vector = prototype_vectors.get(phrase)
                if vector is None:
                    continue
                score = cosine_similarity(query_vector, vector)
                if score > best_score:
                    best_score = score
                    best_phrase = phrase
            if best_score < generation.threshold:
                continue
            candidates.append(
                IntentCandidate(
                    intent=prototype.intent,
                    confidence=min(0.91, 0.46 + best_score * 0.5),
                    source="vector",
                    evidence=[
                        f"prototype:{best_phrase}",
                        f"cosine_similarity:{best_score:.3f}",
                    ],
                    domain=prototype.domain,
                )
            )
        return candidates

    def _warmup_failure(
        self,
        started: float,
        error_category: EmbeddingErrorCategory,
        message: str,
        *,
        fingerprint: str = "",
    ) -> SemanticWarmupResult:
        result = SemanticWarmupResult(
            ready=False,
            fingerprint=fingerprint,
            error_category=error_category,
            message=message,
            elapsed_ms=_elapsed_ms(started),
        )
        self.last_warmup_result = result
        logger.warning(
            "Routing semantic warmup failed open: fingerprint=%s category=%s "
            "message=%s elapsed_ms=%.1f",
            fingerprint[:12] or "none",
            error_category,
            message,
            result.elapsed_ms,
        )
        return result


def embedding_fingerprint(
    embeddings: object,
    *,
    dimensions: int | None = None,
) -> str:
    config = getattr(embeddings, "config", None)
    if isinstance(config, ResolvedEmbeddingConfig) and dimensions is not None:
        return build_embedding_space_spec(
            purpose="routing",
            config=config,
            dimensions=dimensions,
        ).fingerprint
    fingerprint = str(getattr(embeddings, "fingerprint", "") or "")
    if fingerprint:
        return fingerprint
    return str(getattr(embeddings, "model", "") or "unknown_embedding_client")


def _unavailable_batch(started: float, reason: str) -> RecallBatch:
    return RecallBatch(
        provider="routing_vector",
        source="vector",
        provider_status="unavailable",
        latency_ms=_elapsed_ms(started),
        degraded_reason=reason,
    )


def _elapsed_ms(started: float) -> float:
    return (time.perf_counter() - started) * 1000
