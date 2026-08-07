from __future__ import annotations

import time
import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.crud import model_capability as capability_crud
from app.models.model_capability import ModelCapabilityCheck
from app.services.model_probe import get_model_probe
from app.services.model_probe.configuration import (
    ProbeTargetResolutionError,
    resolve_probe_target,
)


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

    try:
        target = await resolve_probe_target(
            db,
            model_id,
            timeout_seconds=timeout_seconds,
            check_thinking=check_thinking,
        )
    except ProbeTargetResolutionError as exc:
        raise ModelValidationError(str(exc)) from exc
    model_type = target.model_type

    try:
        probe = get_model_probe(model_type)
    except ValueError as exc:
        raise ModelValidationError("unsupported_model_type") from exc

    started = time.perf_counter()
    outcome = await probe.run(target.config)

    raw_summary: dict[str, Any] = {
        "contract_version": "model-probe-v2",
        "requested_thinking_check": bool(check_thinking),
        "configured_thinking": target.configured_thinking,
        "model_type": model_type,
        "configuration_fingerprint": target.configuration_fingerprint,
        **outcome.summary,
    }
    result: dict[str, Any] = {
        "model_id": target.model_db_id,
        "provider": target.provider,
        "provider_model_id": target.provider_model_id,
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
