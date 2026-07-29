from __future__ import annotations

import time
import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.crud import model as model_crud
from app.crud import model_capability as capability_crud
from app.crud import provider as provider_crud
from app.crud import provider_connection as connection_crud
from app.infra.llm.embedding_config import build_explicit_embedding_config
from app.models.model_capability import ModelCapabilityCheck
from app.services.model_probe import ProbeConfig, get_model_probe
from app.utils.crypto import decrypt_api_key


class ModelValidationError(ValueError):
    """Raised when a model capability check cannot be started."""


async def validate_model_capability(
    db: AsyncSession,
    model_id: uuid.UUID,
    *,
    check_thinking: bool = True,
    timeout_seconds: float = 45,
) -> ModelCapabilityCheck:
    """Resolve one configured model, run its modality probe, and persist the result."""

    model = await model_crud.get_model_by_id(db, model_id)
    if model is None:
        raise ModelValidationError("model_not_found")

    connection = (
        await connection_crud.get_connection(db, model.connection_id)
        if model.connection_id
        else None
    )
    provider_key = connection.provider if connection is not None else model.provider
    provider = await provider_crud.get_provider(db, provider_key)
    if provider is None:
        raise ModelValidationError("provider_not_found")

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

    try:
        probe = get_model_probe(model_type)
    except ValueError as exc:
        raise ModelValidationError("unsupported_model_type") from exc

    started = time.perf_counter()
    outcome = await probe.run(
        ProbeConfig(
            provider=provider_key,
            provider_model_id=str(model.model_id),
            api_key=api_key,
            base_url=base_url,
            is_openai_compatible=bool(provider.is_openai_compatible),
            timeout_seconds=timeout_seconds,
            check_thinking=bool(check_thinking and model_type != "embedding"),
            extra_headers=extra_headers,
            expected_embedding_dimensions=(
                embedding_config.dimension if embedding_config is not None else None
            ),
            embedding_config=embedding_config,
        )
    )

    raw_summary: dict[str, Any] = {
        "contract_version": "model-probe-v2",
        "requested_thinking_check": bool(check_thinking),
        "configured_thinking": bool(model.thinking),
        "model_type": model_type,
        **outcome.summary,
    }
    result: dict[str, Any] = {
        "model_id": model.id,
        "provider": provider_key,
        "provider_model_id": str(model.model_id),
        "probe_kind": outcome.probe_kind,
        "probe_ok": outcome.probe_ok,
        "embedding_dimensions": outcome.embedding_dimensions,
        "error_category": outcome.error_category,
        # Legacy compatibility: old clients treated chat_ok as generic validation
        # success, including for models that are not chat models.
        "chat_ok": outcome.probe_ok,
        "thinking_request_ok": outcome.thinking_request_ok,
        "reasoning_text_ok": outcome.reasoning_text_ok,
        "streaming_reasoning_ok": outcome.streaming_reasoning_ok,
        "reasoning_field_path": outcome.reasoning_field_path,
        "latency_ms": _elapsed_ms(started),
        "error_type": outcome.error_type,
        "last_error": outcome.last_error,
        "raw_summary": raw_summary,
    }
    return await capability_crud.create_capability_check(db, result)


def _elapsed_ms(started: float) -> int:
    return int((time.perf_counter() - started) * 1000)
