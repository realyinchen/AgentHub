from __future__ import annotations

import asyncio
import time
import uuid
from collections.abc import Mapping
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage
from sqlalchemy.ext.asyncio import AsyncSession

from app.crud import model as model_crud
from app.crud import model_capability as capability_crud
from app.crud import provider as provider_crud
from app.infra.llm.factory import create_llm_from_config
from app.models.model_capability import ModelCapabilityCheck
from app.utils.crypto import decrypt_api_key
from app.utils.message import convert_message_content_to_string, extract_thinking


BASIC_PROMPT = "Reply with exactly: OK"
THINKING_PROMPT = (
    "Use your reasoning mode if it is available. Decide whether 17 + 25 = 42. "
    "Final answer must be exactly: OK"
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
    """Run a real model call and persist the observed capability result."""
    model = await model_crud.get_model_by_id(db, model_id)
    if model is None:
        raise ModelValidationError("model_not_found")

    provider = await provider_crud.get_provider(db, model.provider)
    if provider is None:
        raise ModelValidationError("provider_not_found")

    started = time.perf_counter()
    result: dict[str, Any] = {
        "model_id": model.id,
        "provider": model.provider,
        "provider_model_id": str(model.model_id),
        "chat_ok": False,
        "thinking_request_ok": None,
        "reasoning_text_ok": None,
        "streaming_reasoning_ok": None,
        "reasoning_field_path": None,
        "raw_summary": {
            "requested_thinking_check": bool(check_thinking),
            "configured_thinking": bool(model.thinking),
            "model_type": str(model.model_type),
        },
    }

    try:
        basic_response = await _invoke_model(
            provider=provider.provider,
            provider_model_id=str(model.model_id),
            api_key=decrypt_api_key(provider.api_key or ""),
            base_url=provider.base_url,
            is_openai_compatible=bool(provider.is_openai_compatible),
            thinking_mode=False,
            prompt=BASIC_PROMPT,
            timeout_seconds=timeout_seconds,
        )
        basic_content = convert_message_content_to_string(basic_response.content)
        result["chat_ok"] = bool(basic_content.strip())
        result["raw_summary"]["chat_content_chars"] = len(basic_content)
        result["raw_summary"]["chat_response_metadata_keys"] = sorted(
            basic_response.response_metadata.keys()
        )
        if not result["chat_ok"]:
            result["error_type"] = "empty_chat_response"
            result["last_error"] = "Model returned an empty basic chat response."
    except Exception as exc:
        result["error_type"] = "chat_request_failed"
        result["last_error"] = _safe_error(exc)
        result["latency_ms"] = _elapsed_ms(started)
        return await capability_crud.create_capability_check(db, result)

    if check_thinking and str(model.model_type) != "embedding":
        try:
            thinking_response = await _invoke_model(
                provider=provider.provider,
                provider_model_id=str(model.model_id),
                api_key=decrypt_api_key(provider.api_key or ""),
                base_url=provider.base_url,
                is_openai_compatible=bool(provider.is_openai_compatible),
                thinking_mode=True,
                prompt=THINKING_PROMPT,
                timeout_seconds=timeout_seconds,
            )
            thinking_text, field_path = _detect_thinking(thinking_response)
            thinking_content = convert_message_content_to_string(
                thinking_response.content
            )
            result["thinking_request_ok"] = True
            result["reasoning_text_ok"] = bool(thinking_text)
            result["reasoning_field_path"] = field_path
            result["raw_summary"].update(
                {
                    "thinking_content_chars": len(thinking_content),
                    "reasoning_chars": len(thinking_text),
                    "thinking_response_metadata_keys": sorted(
                        thinking_response.response_metadata.keys()
                    ),
                    "thinking_additional_kwargs_keys": sorted(
                        thinking_response.additional_kwargs.keys()
                    ),
                }
            )
        except Exception as exc:
            result["thinking_request_ok"] = False
            result["reasoning_text_ok"] = False
            result["error_type"] = result.get("error_type") or "thinking_request_failed"
            result["last_error"] = _safe_error(exc)

    result["latency_ms"] = _elapsed_ms(started)
    return await capability_crud.create_capability_check(db, result)


async def _invoke_model(
    *,
    provider: str,
    provider_model_id: str,
    api_key: str,
    base_url: str | None,
    is_openai_compatible: bool,
    thinking_mode: bool,
    prompt: str,
    timeout_seconds: float,
) -> AIMessage:
    llm = create_llm_from_config(
        provider=provider,
        model_id=provider_model_id,
        api_key=api_key,
        base_url=base_url,
        is_openai_compatible=is_openai_compatible,
        thinking_mode=thinking_mode,
    )
    response = await asyncio.wait_for(
        llm.ainvoke([HumanMessage(content=prompt)]),
        timeout=timeout_seconds,
    )
    if not isinstance(response, AIMessage):
        raise TypeError(f"Expected AIMessage, got {type(response).__name__}")
    return response


def _detect_thinking(message: AIMessage) -> tuple[str, str | None]:
    """Return reasoning text and where it was found."""
    structured = _extract_structured_thinking(message.content)
    if structured:
        return structured, "content[type=thinking]"

    reasoning_attr = getattr(message, "reasoning_content", None)
    attr_text = _stringify_reasoning(reasoning_attr)
    if attr_text:
        return attr_text, "reasoning_content"

    thinking = extract_thinking(message)
    if thinking:
        return thinking, "additional_kwargs.reasoning_content"

    for key in ("reasoning_content", "reasoning"):
        value = message.additional_kwargs.get(key)
        text = _stringify_reasoning(value)
        if text:
            return text, f"additional_kwargs.{key}"

    details = message.additional_kwargs.get("reasoning_details")
    details_text = _extract_reasoning_details(details)
    if details_text:
        return details_text, "additional_kwargs.reasoning_details"

    return "", None


def _extract_structured_thinking(content: Any) -> str:
    if not isinstance(content, list):
        return ""

    parts: list[str] = []
    for block in content:
        if not isinstance(block, Mapping) or block.get("type") != "thinking":
            continue
        text = block.get("thinking") or block.get("text") or block.get("content")
        if isinstance(text, str) and text.strip():
            parts.append(text)
    return "".join(parts).strip()


def _extract_reasoning_details(value: Any) -> str:
    if not isinstance(value, list):
        return ""

    parts: list[str] = []
    for item in value:
        if isinstance(item, Mapping):
            text = item.get("text") or item.get("reasoning") or item.get("content")
            if isinstance(text, str) and text.strip():
                parts.append(text)
        elif isinstance(item, str) and item.strip():
            parts.append(item)
    return "".join(parts).strip()


def _stringify_reasoning(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        return "".join(str(item) for item in value if item).strip()
    if value:
        return str(value).strip()
    return ""


def _elapsed_ms(started: float) -> int:
    return int((time.perf_counter() - started) * 1000)


def _safe_error(exc: Exception) -> str:
    message = str(exc) or exc.__class__.__name__
    if len(message) > 1000:
        return f"{message[:997]}..."
    return message
