from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal, Mapping

if TYPE_CHECKING:
    from app.infra.llm.embedding_config import ResolvedEmbeddingConfig


ProbeKind = Literal["chat", "embedding"]
ProbeErrorCategory = Literal[
    "network",
    "auth",
    "model",
    "rate_limit",
    "dimension",
    "provider",
]


@dataclass(frozen=True)
class ProbeConfig:
    """Transport-neutral input required by a model capability probe."""

    provider: str
    provider_model_id: str
    api_key: str
    base_url: str | None
    is_openai_compatible: bool
    timeout_seconds: float
    configured_thinking: bool = False
    check_thinking: bool = True
    extra_headers: Mapping[str, str] = field(default_factory=dict)
    expected_embedding_dimensions: int | None = None
    embedding_config: ResolvedEmbeddingConfig | None = None


@dataclass
class ProbeOutcome:
    """Common output emitted by every modality-specific probe."""

    probe_kind: ProbeKind
    probe_ok: bool
    embedding_dimensions: int | None = None
    error_category: ProbeErrorCategory | None = None
    error_type: str | None = None
    last_error: str | None = None
    thinking_request_ok: bool | None = None
    reasoning_text_ok: bool | None = None
    streaming_reasoning_ok: bool | None = None
    reasoning_field_path: str | None = None
    summary: dict[str, Any] = field(default_factory=dict)


__all__ = [
    "ProbeConfig",
    "ProbeErrorCategory",
    "ProbeKind",
    "ProbeOutcome",
]
