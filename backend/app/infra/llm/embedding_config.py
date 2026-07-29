"""Resolve the single effective embedding configuration.

This module only translates configuration into an immutable value object.  It
does not create clients, make network requests, or mutate application state.
Database-backed model configuration wins; environment configuration is a
startup-safe fallback when no active database embedding model exists.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Literal, Mapping

from app.infra.config import Settings, get_settings
from app.infra.llm.manager import ModelManager, get_model_manager
from app.infra.llm.provider_adapters import get_provider_adapter


EmbeddingConfigSource = Literal["database", "environment"]


@dataclass(frozen=True)
class ResolvedEmbeddingConfig:
    """Transport-ready embedding configuration.

    ``dimension`` is the model output dimension when it is explicitly known.
    It is intentionally ``None`` for legacy database model rows that do not
    declare a dimension.  Unknown is safer than assuming that a remote model
    matches the fixed pgvector schema.
    """

    source: EmbeddingConfigSource
    model: str
    provider: str
    base_url: str | None
    api_key: str | None = field(repr=False)
    headers: dict[str, str]
    dimension: int | None
    model_revision: str
    fingerprint: str
    model_id: str
    connection_id: str | None = None


def resolve_embedding_config(
    model_id: str = "",
    *,
    manager: ModelManager | None = None,
    settings: Settings | None = None,
) -> ResolvedEmbeddingConfig | None:
    """Resolve an embedding model into one explicit transport contract.

    Args:
        model_id: Optional database model UUID/provider model identifier.
            When supplied, failure to resolve that exact model does not silently
            fall back to a different environment model.
        manager: Optional manager override for tests and probes.
        settings: Optional settings override for tests and probes.

    Returns:
        A database-derived config, an environment fallback config, or ``None``.
    """

    resolved_settings = settings or get_settings()
    resolved_manager = manager or get_model_manager()
    database_config = _resolve_database_config(
        model_id=model_id,
        manager=resolved_manager,
        settings=resolved_settings,
    )
    if database_config is not None:
        return database_config
    if model_id:
        return None
    return _resolve_environment_config(resolved_settings)


def build_explicit_embedding_config(
    *,
    provider: str,
    configured_model_id: str,
    api_key: str | None,
    base_url: str | None = None,
    headers: Mapping[str, Any] | None = None,
    is_openai_compatible: bool = False,
    dimension: int | None = None,
    model_revision: str = "",
    source: EmbeddingConfigSource = "database",
    model_id: str = "",
    connection_id: str | None = None,
    settings: Settings | None = None,
) -> ResolvedEmbeddingConfig:
    """Build a config from explicit values without consulting runtime caches.

    Model validation uses this function because it may probe a newly edited or
    inactive database row that is deliberately absent from ModelManager.
    Provider normalization, attribution headers, and fingerprinting therefore
    remain identical to the application runtime.
    """

    normalized_provider = str(provider).strip()
    normalized_configured_model = str(configured_model_id).strip()
    if not normalized_provider:
        raise ValueError("provider is required for an embedding configuration")
    if not normalized_configured_model:
        raise ValueError("configured_model_id is required for an embedding configuration")

    resolved_settings = settings or get_settings()
    adapter = get_provider_adapter(normalized_provider)
    provider_model_id = adapter.normalize_model_id(
        normalized_provider,
        normalized_configured_model,
    )
    transport_model = adapter.litellm_model_name(
        normalized_provider,
        provider_model_id,
        is_openai_compatible,
    )
    adapter_headers = dict(
        adapter.extra_litellm_params(resolved_settings).get("extra_headers") or {}
    )
    resolved_headers = _merge_headers(adapter_headers, headers)
    return _build_config(
        source=source,
        model=transport_model,
        provider=normalized_provider,
        base_url=base_url,
        api_key=api_key,
        headers=resolved_headers,
        dimension=dimension,
        model_revision=model_revision,
        model_id=model_id or normalized_configured_model,
        connection_id=connection_id,
    )


def _resolve_database_config(
    *,
    model_id: str,
    manager: ModelManager,
    settings: Settings,
) -> ResolvedEmbeddingConfig | None:
    if not getattr(manager, "_initialized", False):
        return None

    selected_id = (
        model_id
        or manager.default_embedding_id
        or manager.get_first_active_embedding_id()
        or ""
    )
    if not selected_id:
        return None

    model_config = manager.get_model(selected_id)
    if model_config is None:
        return None
    if str(getattr(model_config, "model_type", "")) != "embedding":
        return None
    if not bool(getattr(model_config, "is_active", True)):
        return None

    connection_id = str(getattr(model_config, "connection_id", "") or "") or None
    connection = manager.get_connection(connection_id)
    provider = str(
        getattr(connection, "provider", "")
        or getattr(model_config, "provider", "")
    ).strip()
    if not provider:
        return None

    provider_config = manager.get_provider(provider)
    configured_model_id = str(getattr(model_config, "model_id", "")).strip()
    if not configured_model_id:
        return None

    is_openai_compatible = bool(
        getattr(provider_config, "is_openai_compatible", False)
    )
    api_key = (
        manager.get_connection_api_key(connection_id)
        or manager.get_api_key(provider)
    )
    base_url = (
        manager.get_connection_base_url(connection_id)
        or manager.get_base_url(provider)
    )
    connection_headers = getattr(connection, "extra_headers_json", None)
    dimension = _declared_dimension(model_config)
    model_revision = str(
        getattr(model_config, "embedding_revision", "")
        or getattr(model_config, "model_revision", "")
        or getattr(settings, "EMBEDDING_SPACE_REVISION", "")
    ).strip()
    return build_explicit_embedding_config(
        provider=provider,
        configured_model_id=configured_model_id,
        api_key=api_key,
        base_url=base_url,
        headers=connection_headers,
        is_openai_compatible=is_openai_compatible,
        dimension=dimension,
        model_revision=model_revision,
        source="database",
        model_id=str(getattr(model_config, "id", selected_id)),
        connection_id=connection_id,
        settings=settings,
    )


def _resolve_environment_config(
    settings: Settings,
) -> ResolvedEmbeddingConfig | None:
    configured_model = str(settings.SYSTEM_DEFAULT_EMBEDDING_MODEL or "").strip()
    if not configured_model:
        return None

    provider, separator, provider_model_id = configured_model.partition("/")
    if not separator or not provider or not provider_model_id:
        return None

    return build_explicit_embedding_config(
        provider=provider,
        configured_model_id=provider_model_id,
        api_key=settings.system_default_embedding_api_key,
        base_url=settings.SYSTEM_DEFAULT_LLM_BASE_URL,
        headers=None,
        is_openai_compatible=provider == "openai-compatible",
        dimension=settings.EMBEDDING_DIMENSION,
        model_revision=str(
            getattr(settings, "EMBEDDING_SPACE_REVISION", "")
        ).strip(),
        source="environment",
        model_id=configured_model,
        connection_id=None,
        settings=settings,
    )


def _build_config(
    *,
    source: EmbeddingConfigSource,
    model: str,
    provider: str,
    base_url: str | None,
    api_key: str | None,
    headers: dict[str, str],
    dimension: int | None,
    model_revision: str,
    model_id: str,
    connection_id: str | None,
) -> ResolvedEmbeddingConfig:
    fingerprint_payload = {
        "source": source,
        "model": model,
        "provider": provider,
        "base_url": base_url or "",
        "api_key_digest": _secret_digest(api_key),
        "headers": sorted(headers.items()),
        "dimension": dimension,
        "model_revision": model_revision,
        "model_id": model_id,
        "connection_id": connection_id or "",
    }
    fingerprint = hashlib.sha256(
        json.dumps(
            fingerprint_payload,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()
    return ResolvedEmbeddingConfig(
        source=source,
        model=model,
        provider=provider,
        base_url=base_url,
        api_key=api_key,
        headers=headers,
        dimension=dimension,
        model_revision=model_revision,
        fingerprint=fingerprint,
        model_id=model_id,
        connection_id=connection_id,
    )


def _declared_dimension(model_config: object) -> int | None:
    """Read future-compatible dimension metadata without inventing a value."""

    for name in ("embedding_dimension", "dimension", "dimensions"):
        value = getattr(model_config, name, None)
        if value is None:
            continue
        try:
            dimension = int(value)
        except (TypeError, ValueError):
            continue
        if dimension > 0:
            return dimension
    return None


def _merge_headers(
    defaults: Mapping[str, Any],
    overrides: object,
) -> dict[str, str]:
    result = {
        str(key): str(value)
        for key, value in defaults.items()
        if value is not None and str(value)
    }
    if isinstance(overrides, Mapping):
        result.update(
            {
                str(key): str(value)
                for key, value in overrides.items()
                if value is not None and str(value)
            }
        )
    return result


def _secret_digest(secret: str | None) -> str:
    if not secret:
        return ""
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()


__all__ = [
    "EmbeddingConfigSource",
    "ResolvedEmbeddingConfig",
    "build_explicit_embedding_config",
    "resolve_embedding_config",
]
