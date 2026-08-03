"""Temporary R7 compatibility bridge for pre-calibration activation."""

from __future__ import annotations

from uuid import UUID

from app.infra.embedding_spaces.contracts import EmbeddingSpaceRecord
from app.infra.embedding_spaces.registry import EmbeddingSpaceRegistry


class LegacyEmbeddingActivationBridge:
    """Keep the old cutover callable isolated until R8 removes it."""

    def __init__(self, registry: EmbeddingSpaceRegistry) -> None:
        self._registry = registry

    async def activate(self, space_id: UUID) -> EmbeddingSpaceRecord:
        return await self._registry.activate(space_id)


__all__ = ["LegacyEmbeddingActivationBridge"]
