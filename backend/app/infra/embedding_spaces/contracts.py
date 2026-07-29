"""Pure contracts and identity rules for embedding spaces."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import TYPE_CHECKING, Literal
from urllib.parse import urlsplit, urlunsplit
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

if TYPE_CHECKING:
    from app.infra.llm.embedding_config import ResolvedEmbeddingConfig

EmbeddingPurpose = Literal["routing", "memory", "documents"]
EmbeddingSpaceStatus = Literal["building", "ready", "active", "failed"]
DistanceMetric = Literal["cosine"]
VectorIndexKind = Literal["hnsw_vector", "hnsw_halfvec", "exact"]

_HNSW_VECTOR_MAX_DIMENSIONS = 2_000
_HNSW_HALFVEC_MAX_DIMENSIONS = 4_000
_PGVECTOR_MAX_DIMENSIONS = 16_000


class EmbeddingSpaceSpec(BaseModel):
    """Immutable identity of one semantic coordinate space."""

    model_config = ConfigDict(frozen=True)

    purpose: EmbeddingPurpose
    provider: str = Field(min_length=1)
    model: str = Field(min_length=1)
    model_revision: str = ""
    model_origin: str = ""
    dimensions: int = Field(ge=1, le=_PGVECTOR_MAX_DIMENSIONS)
    distance_metric: DistanceMetric = "cosine"
    normalized: bool = False
    fingerprint: str = Field(min_length=64, max_length=64)
    transport_fingerprint: str = Field(default="", max_length=64)
    index_kind: VectorIndexKind

    @model_validator(mode="after")
    def validate_index_capacity(self) -> "EmbeddingSpaceSpec":
        if (
            self.index_kind == "hnsw_vector"
            and self.dimensions > _HNSW_VECTOR_MAX_DIMENSIONS
        ):
            raise ValueError("hnsw_vector supports at most 2000 dimensions")
        if (
            self.index_kind == "hnsw_halfvec"
            and self.dimensions > _HNSW_HALFVEC_MAX_DIMENSIONS
        ):
            raise ValueError("hnsw_halfvec supports at most 4000 dimensions")
        return self


class EmbeddingSpaceRecord(BaseModel):
    """Persisted lifecycle state for one embedding generation."""

    id: UUID
    generation: int = Field(ge=1)
    spec: EmbeddingSpaceSpec
    table_name: str = Field(pattern=r"^[a-z][a-z0-9_]{0,62}$")
    status: EmbeddingSpaceStatus
    source_space_id: UUID | None = None
    source_table_name: str | None = None
    document_count: int = Field(default=0, ge=0)
    error: str = ""
    created_at: datetime | None = None
    updated_at: datetime | None = None
    activated_at: datetime | None = None


class EmbeddingSpaceBuildResult(BaseModel):
    """Output of one rebuild job."""

    space_id: UUID
    status: Literal["ready", "failed"]
    source_count: int = Field(default=0, ge=0)
    embedded_count: int = Field(default=0, ge=0)
    indexed: bool = False
    error: str = ""


class VectorSourceDocument(BaseModel):
    """Dimension-free source document used by rebuild jobs."""

    id: str = Field(min_length=1)
    collection_name: str = Field(default="documents", min_length=1)
    content: str
    metadata: dict = Field(default_factory=dict)


def build_embedding_space_spec(
    *,
    purpose: EmbeddingPurpose,
    config: ResolvedEmbeddingConfig,
    dimensions: int,
    model_revision: str | None = None,
    distance_metric: DistanceMetric = "cosine",
    normalized: bool = False,
) -> EmbeddingSpaceSpec:
    """Build a secret-free semantic identity from observed model output."""

    if dimensions <= 0 or dimensions > _PGVECTOR_MAX_DIMENSIONS:
        raise ValueError(
            "Observed embedding dimensions must be between 1 and 16000 "
            f"(actual={dimensions})"
        )
    origin = _normalize_origin(config.base_url)
    payload = {
        "purpose": purpose,
        "provider": config.provider.strip().lower(),
        "model": config.model.strip(),
        "model_revision": (
            config.model_revision if model_revision is None else model_revision
        ).strip(),
        "model_origin": origin,
        "dimensions": dimensions,
        "distance_metric": distance_metric,
        "normalized": normalized,
    }
    fingerprint = hashlib.sha256(
        json.dumps(
            payload,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()
    return EmbeddingSpaceSpec(
        **payload,
        fingerprint=fingerprint,
        transport_fingerprint=config.fingerprint,
        index_kind=_select_index_kind(dimensions),
    )


def _select_index_kind(dimensions: int) -> VectorIndexKind:
    if dimensions <= _HNSW_VECTOR_MAX_DIMENSIONS:
        return "hnsw_vector"
    if dimensions <= _HNSW_HALFVEC_MAX_DIMENSIONS:
        return "hnsw_halfvec"
    return "exact"


def _normalize_origin(base_url: str | None) -> str:
    if not base_url:
        return ""
    value = base_url.strip().rstrip("/")
    try:
        parts = urlsplit(value)
    except ValueError:
        return value.lower()
    return urlunsplit(
        (
            parts.scheme.lower(),
            parts.netloc.lower(),
            parts.path.rstrip("/"),
            "",
            "",
        )
    )


__all__ = [
    "DistanceMetric",
    "EmbeddingPurpose",
    "EmbeddingSpaceBuildResult",
    "EmbeddingSpaceRecord",
    "EmbeddingSpaceSpec",
    "EmbeddingSpaceStatus",
    "VectorSourceDocument",
    "VectorIndexKind",
    "build_embedding_space_spec",
]
