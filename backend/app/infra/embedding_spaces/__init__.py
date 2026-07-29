"""Versioned embedding-space infrastructure.

The package separates pure space identity, registry persistence, physical
schema management, rebuild work, and runtime activation.  Callers should use
the runtime facade instead of constructing table names or changing vector
schemas themselves.
"""

from app.infra.embedding_spaces.contracts import (
    EmbeddingPurpose,
    EmbeddingSpaceBuildResult,
    EmbeddingSpaceRecord,
    EmbeddingSpaceSpec,
    EmbeddingSpaceStatus,
    VectorIndexKind,
    build_embedding_space_spec,
)
__all__ = [
    "EmbeddingPurpose",
    "EmbeddingSpaceBuildResult",
    "EmbeddingSpaceRecord",
    "EmbeddingSpaceSpec",
    "EmbeddingSpaceStatus",
    "VectorIndexKind",
    "build_embedding_space_spec",
]
