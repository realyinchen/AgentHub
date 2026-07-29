"""Remote-embedding prototype index and bounded vector recall."""

from __future__ import annotations

import asyncio
import logging
import math
import time
from dataclasses import dataclass

from app.infra.embedding_spaces.contracts import build_embedding_space_spec
from app.infra.llm.embedding import get_configured_embeddings
from app.infra.llm.embedding_config import ResolvedEmbeddingConfig
from app.infra.llm.embedding_errors import (
    EmbeddingErrorCategory,
    classify_embedding_error,
    safe_embedding_error,
)
from app.infra.llm.manager import get_model_manager
from app.services.routing.config import (
    SEMANTIC_WARMUP_TIMEOUT_SECONDS,
    VECTOR_CANDIDATE_THRESHOLD,
    VECTOR_REQUEST_TIMEOUT_SECONDS,
)
from app.services.routing.contracts import IntentCandidate
from app.services.routing.interaction_contracts import RecallBatch
from app.services.routing.recall_projection import recall_batch
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

    def __init__(self) -> None:
        self.prototype_vectors: dict[str, list[float]] = {}
        self.model_key = ""
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
        first_vector = next(iter(self.prototype_vectors.values()), [])
        model_key = self.model_key
        result = SemanticWarmupResult(
            ready=bool(self.prototype_vectors),
            fingerprint=model_key,
            dimensions=len(first_vector) or None,
            elapsed_ms=_elapsed_ms(started),
        )
        self.last_warmup_result = result
        logger.info(
            "Routing semantic index ready: fingerprint=%s prototypes=%d "
            "dimensions=%d elapsed_ms=%.1f",
            model_key[:12],
            len(self.prototype_vectors),
            len(first_vector),
            result.elapsed_ms,
        )
        return result

    async def ensure_index(self, embeddings: object, model_key: str) -> None:
        if self.prototype_vectors and self.model_key == model_key:
            return
        async with self._lock:
            if self.prototype_vectors and self.model_key == model_key:
                return
            phrases = [phrase for item in PROTOTYPES for phrase in item.phrases]
            vectors = await embeddings.aembed_documents(phrases)  # type: ignore[attr-defined]
            dimensions = {len(vector) for vector in vectors}
            if len(dimensions) != 1:
                raise ValueError(
                    "Routing prototypes returned inconsistent dimensions"
                )
            observed_dimensions = next(iter(dimensions), 0)
            if observed_dimensions <= 0:
                raise ValueError("Routing prototypes returned empty vectors")
            resolved_key = model_key or embedding_fingerprint(
                embeddings,
                dimensions=observed_dimensions,
            )
            new_index = dict(zip(phrases, vectors, strict=True))
            self.prototype_vectors = new_index
            self.model_key = resolved_key

    def _rank(self, query_vector: list[float]) -> list[IntentCandidate]:
        candidates: list[IntentCandidate] = []
        for prototype in PROTOTYPES:
            best_score = 0.0
            best_phrase = ""
            for phrase in prototype.phrases:
                vector = self.prototype_vectors.get(phrase)
                if vector is None:
                    continue
                score = cosine(query_vector, vector)
                if score > best_score:
                    best_score = score
                    best_phrase = phrase
            if best_score < VECTOR_CANDIDATE_THRESHOLD:
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


def cosine(left: list[float], right: list[float]) -> float:
    if not left or len(left) != len(right):
        return 0.0
    dot = sum(a * b for a, b in zip(left, right, strict=True))
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if not left_norm or not right_norm:
        return 0.0
    return max(-1.0, min(1.0, dot / (left_norm * right_norm)))


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
