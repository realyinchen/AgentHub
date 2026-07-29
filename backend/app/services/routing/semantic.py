"""Layer 1 facade composing independent keyword and vector recall providers."""

from __future__ import annotations

import time

from app.services.routing.contracts import IntentCandidate, RoutingQuery
from app.services.routing.interaction_contracts import RecallBatch
from app.services.routing.keyword_recall import recall_keywords
from app.services.routing.recall_projection import merge_candidates, recall_batch
from app.services.routing.vector_recall import (
    SemanticWarmupResult,
    VectorPrototypeRecall,
)


class InMemorySemanticRecall:
    """Compose lexical recall with an immutable remote-embedding index.

    The public facade remains replaceable through ``SemanticRecallProvider``;
    persistent Chroma/FAISS storage is unnecessary for the tiny fixed catalog.
    """

    def __init__(self) -> None:
        self._vector = VectorPrototypeRecall()
        self._last_vector_batch = self._vector.last_batch

    @property
    def last_warmup_result(self) -> SemanticWarmupResult:
        return self._vector.last_warmup_result

    @property
    def _prototype_vectors(self) -> dict[str, list[float]]:
        """Compatibility view for focused embedding-runtime tests."""

        return self._vector.prototype_vectors

    @property
    def _vector_model_key(self) -> str:
        """Compatibility view for focused embedding-runtime tests."""

        return self._vector.model_key

    async def recall(self, query: RoutingQuery) -> list[IntentCandidate]:
        candidates, _ = await self.recall_with_batches(query)
        return candidates

    async def recall_with_batches(
        self,
        query: RoutingQuery,
    ) -> tuple[list[IntentCandidate], list[RecallBatch]]:
        keyword_started = time.perf_counter()
        keyword = recall_keywords(query.text)
        keyword_batch = recall_batch(
            provider="routing_keyword",
            source="keyword",
            candidates=keyword,
            latency_ms=(time.perf_counter() - keyword_started) * 1000,
        )
        vector = await self._vector_candidates(query.text)
        return (
            merge_candidates([*keyword, *vector]),
            [keyword_batch, self._last_vector_batch],
        )

    async def warm(self) -> SemanticWarmupResult:
        result = await self._vector.warm()
        self._last_vector_batch = self._vector.last_batch
        return result

    async def _vector_candidates(self, text: str) -> list[IntentCandidate]:
        candidates = await self._vector.recall(text)
        self._last_vector_batch = self._vector.last_batch
        return candidates

    async def _ensure_index(self, embeddings: object, model_key: str) -> None:
        await self._vector.ensure_index(embeddings, model_key)


__all__ = ["InMemorySemanticRecall", "SemanticWarmupResult"]
