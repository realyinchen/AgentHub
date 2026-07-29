from __future__ import annotations

from typing import Protocol

from app.services.routing.contracts import IntentCandidate, RoutingQuery
from app.services.routing.interaction_contracts import RecallBatch


class SemanticRecallProvider(Protocol):
    """Layer 1 port. Implementations only return scored intent evidence."""

    async def recall(self, query: RoutingQuery) -> list[IntentCandidate]: ...


class ObservableSemanticRecallProvider(SemanticRecallProvider, Protocol):
    """Layer 1 provider that distinguishes no-match from provider degradation."""

    async def recall_with_batches(
        self,
        query: RoutingQuery,
    ) -> tuple[list[IntentCandidate], list[RecallBatch]]: ...


class RouterModelProvider(Protocol):
    """Optional Layer 2 port for a future routing model.

    A provider cannot execute tools or create an ActionPlan. Its only output is
    additional intent evidence using the shared candidate contract.
    """

    async def classify(self, query: RoutingQuery) -> list[IntentCandidate]: ...
