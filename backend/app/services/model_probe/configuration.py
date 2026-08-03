from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.crud import model as model_crud
from app.crud import provider as provider_crud
from app.crud import provider_connection as connection_crud
from app.infra.llm.embedding_config import build_explicit_embedding_config
from app.services.model_probe.contracts import ProbeConfig
from app.utils.crypto import decrypt_api_key


class ProbeTargetResolutionError(ValueError):
    """Raised when a configured model cannot be resolved into a probe target."""


@dataclass(frozen=True)
class ResolvedProbeTarget:
    model_db_id: uuid.UUID
    provider: str
    provider_model_id: str
    model_type: str
    configured_thinking: bool
    connection_id: uuid.UUID | None
    configuration_fingerprint: str
    config: ProbeConfig


async def resolve_probe_target(
    db: AsyncSession,
    model_id: uuid.UUID,
    *,
    timeout_seconds: float,
    check_thinking: bool,
) -> ResolvedProbeTarget:
    model = await model_crud.get_model_by_id(db, model_id)
    if model is None:
        raise ProbeTargetResolutionError("model_not_found")

    connection = (
        await connection_crud.get_connection(db, model.connection_id)
        if model.connection_id
        else None
    )
    provider_key = connection.provider if connection is not None else model.provider
    provider = await provider_crud.get_provider(db, provider_key)
    if provider is None:
        raise ProbeTargetResolutionError("provider_not_found")

    encrypted_api_key = (
        connection.api_key
        if connection is not None and connection.api_key
        else provider.api_key
    )
    api_key = decrypt_api_key(encrypted_api_key or "")
    base_url = (
        connection.base_url
        if connection is not None and connection.base_url
        else provider.base_url
    )
    extra_headers = {
        str(key): str(value)
        for key, value in (
            (connection.extra_headers_json or {}).items()
            if connection is not None
            else ()
        )
        if value is not None
    }
    model_type = str(model.model_type)
    embedding_config = (
        build_explicit_embedding_config(
            provider=provider_key,
            configured_model_id=str(model.model_id),
            api_key=api_key,
            base_url=base_url,
            headers=extra_headers,
            is_openai_compatible=bool(provider.is_openai_compatible),
            model_id=str(model.id),
            connection_id=(
                str(model.connection_id) if model.connection_id else None
            ),
        )
        if model_type == "embedding"
        else None
    )
    fingerprint = _configuration_fingerprint(
        provider=provider_key,
        provider_model_id=str(model.model_id),
        model_type=model_type,
        base_url=base_url,
        is_openai_compatible=bool(provider.is_openai_compatible),
        connection_id=(
            str(model.connection_id) if model.connection_id else None
        ),
        configured_thinking=bool(model.thinking),
        api_key=api_key,
        extra_headers=extra_headers,
    )
    return ResolvedProbeTarget(
        model_db_id=model.id,
        provider=provider_key,
        provider_model_id=str(model.model_id),
        model_type=model_type,
        configured_thinking=bool(model.thinking),
        connection_id=model.connection_id,
        configuration_fingerprint=fingerprint,
        config=ProbeConfig(
            provider=provider_key,
            provider_model_id=str(model.model_id),
            api_key=api_key,
            base_url=base_url,
            is_openai_compatible=bool(provider.is_openai_compatible),
            timeout_seconds=timeout_seconds,
            configured_thinking=bool(model.thinking),
            check_thinking=bool(check_thinking and model_type != "embedding"),
            extra_headers=extra_headers,
            expected_embedding_dimensions=(
                embedding_config.dimension if embedding_config is not None else None
            ),
            embedding_config=embedding_config,
        ),
    )


def _configuration_fingerprint(
    *,
    provider: str,
    provider_model_id: str,
    model_type: str,
    base_url: str | None,
    is_openai_compatible: bool,
    connection_id: str | None,
    configured_thinking: bool,
    api_key: str,
    extra_headers: dict[str, str],
) -> str:
    material = {
        "provider": provider,
        "provider_model_id": provider_model_id,
        "model_type": model_type,
        "base_url": str(base_url or "").rstrip("/"),
        "is_openai_compatible": is_openai_compatible,
        "connection_id": connection_id,
        "configured_thinking": configured_thinking,
        "credential_hash": hashlib.sha256(api_key.encode("utf-8")).hexdigest(),
        "headers_hash": hashlib.sha256(
            json.dumps(
                extra_headers,
                ensure_ascii=True,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest(),
    }
    return hashlib.sha256(
        json.dumps(
            material,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


__all__ = [
    "ProbeTargetResolutionError",
    "ResolvedProbeTarget",
    "resolve_probe_target",
]
