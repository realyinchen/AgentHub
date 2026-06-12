"""Provider-specific LLM adapter hooks.

LiteLLM gives this project a common transport, but reasoning/thinking is not
standardized across providers. This module keeps provider-specific request
parameters and response normalization out of the main factory.
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import AsyncIterator, Iterator, Mapping
from dataclasses import dataclass
from typing import Any

import httpx
from langchain_litellm import ChatLiteLLM


logger = logging.getLogger(__name__)


class OpenRouterReasoningChatLiteLLM(ChatLiteLLM):
    """Use OpenRouter's raw response shape when reasoning details are requested."""

    def completion_with_retry(self, run_manager=None, **kwargs: Any) -> Any:
        if _should_use_openrouter_reasoning(kwargs):
            logger.debug(
                "Using raw OpenRouter reasoning completion; stream=%s",
                kwargs.get("stream"),
            )
            if kwargs.get("stream"):
                return _openrouter_stream_completion(kwargs)
            return _openrouter_completion(kwargs)
        return super().completion_with_retry(run_manager=run_manager, **kwargs)

    async def acompletion_with_retry(self, run_manager=None, **kwargs: Any) -> Any:
        if _should_use_openrouter_reasoning(kwargs):
            logger.debug(
                "Using raw OpenRouter reasoning completion; stream=%s",
                kwargs.get("stream"),
            )
            if kwargs.get("stream"):
                return _openrouter_astream_completion(kwargs)
            return await _openrouter_acompletion(kwargs)
        return await super().acompletion_with_retry(
            run_manager=run_manager,
            **kwargs,
        )


@dataclass(frozen=True)
class ProviderAdapter:
    """Default adapter for native LiteLLM and OpenAI-compatible providers."""

    chat_model_cls: type[ChatLiteLLM] = ChatLiteLLM
    requires_real_api_key: bool = False

    def normalize_model_id(self, provider: str, configured_model_id: str) -> str:
        if configured_model_id.startswith(f"{provider}/"):
            return configured_model_id.split("/", 1)[1]
        if configured_model_id.startswith("openai/"):
            return configured_model_id.split("/", 1)[1]
        return configured_model_id

    def litellm_model_name(
        self,
        provider: str,
        provider_model_id: str,
        is_openai_compatible: bool,
    ) -> str:
        if is_openai_compatible:
            return f"openai/{provider_model_id}"
        return f"{provider}/{provider_model_id}"

    def model_kwargs(self, thinking_mode: bool) -> dict[str, Any]:
        return {"stream_options": {"include_usage": True}}

    def streaming_enabled(self, thinking_mode: bool) -> bool:
        return True

    def extra_litellm_params(self, settings: Any) -> dict[str, Any]:
        return {}


@dataclass(frozen=True)
class DashScopeAdapter(ProviderAdapter):
    """DashScope uses extra_body.enable_thinking."""

    def model_kwargs(self, thinking_mode: bool) -> dict[str, Any]:
        kwargs = super().model_kwargs(thinking_mode)
        kwargs["extra_body"] = {"enable_thinking": thinking_mode}
        return kwargs


@dataclass(frozen=True)
class OpenRouterAdapter(ProviderAdapter):
    """OpenRouter uses reasoning/include_reasoning and reasoning_details."""

    chat_model_cls: type[ChatLiteLLM] = OpenRouterReasoningChatLiteLLM
    requires_real_api_key: bool = True

    def model_kwargs(self, thinking_mode: bool) -> dict[str, Any]:
        kwargs = super().model_kwargs(thinking_mode)
        if thinking_mode:
            kwargs["extra_body"] = {
                "reasoning": {"enabled": True},
                "include_reasoning": True,
            }
        return kwargs

    def streaming_enabled(self, thinking_mode: bool) -> bool:
        return True

    def extra_litellm_params(self, settings: Any) -> dict[str, Any]:
        headers: dict[str, str] = {}
        if settings.OPENROUTER_HTTP_REFERER:
            headers["HTTP-Referer"] = settings.OPENROUTER_HTTP_REFERER
        if settings.OPENROUTER_X_TITLE:
            headers["X-Title"] = settings.OPENROUTER_X_TITLE
        return {"extra_headers": headers} if headers else {}


_ADAPTERS: dict[str, ProviderAdapter] = {
    "dashscope": DashScopeAdapter(),
    "openrouter": OpenRouterAdapter(),
}


def get_provider_adapter(provider: str) -> ProviderAdapter:
    return _ADAPTERS.get(provider, ProviderAdapter())


def _should_use_openrouter_reasoning(kwargs: Mapping[str, Any]) -> bool:
    extra_body = kwargs.get("extra_body")
    return isinstance(extra_body, dict) and bool(
        extra_body.get("include_reasoning") or extra_body.get("reasoning")
    )


def _openrouter_completion(kwargs: Mapping[str, Any]) -> dict[str, Any]:
    payload, headers, url = _build_openrouter_request(kwargs, stream=False)
    with httpx.Client(timeout=kwargs.get("timeout") or 120) as client:
        response = client.post(url, headers=headers, json=payload)
        response.raise_for_status()
        data = response.json()
        _log_openrouter_reasoning_response("sync", payload, data)
        return _normalize_openrouter_response(data)


async def _openrouter_acompletion(kwargs: Mapping[str, Any]) -> dict[str, Any]:
    payload, headers, url = _build_openrouter_request(kwargs, stream=False)
    async with httpx.AsyncClient(timeout=kwargs.get("timeout") or 120) as client:
        response = await client.post(url, headers=headers, json=payload)
        response.raise_for_status()
        data = response.json()
        _log_openrouter_reasoning_response("async", payload, data)
        return _normalize_openrouter_response(data)


def _openrouter_stream_completion(
    kwargs: Mapping[str, Any],
) -> Iterator[dict[str, Any]]:
    payload, headers, url = _build_openrouter_request(kwargs, stream=True)
    model = str(payload.get("model") or "")
    with httpx.Client(timeout=kwargs.get("timeout") or 120) as client:
        with client.stream("POST", url, headers=headers, json=payload) as response:
            response.raise_for_status()
            for line in response.iter_lines():
                chunk = _parse_openrouter_sse_line(line, model)
                if chunk is _OPENROUTER_SSE_DONE:
                    break
                if chunk:
                    yield chunk


async def _openrouter_astream_completion(
    kwargs: Mapping[str, Any],
) -> AsyncIterator[dict[str, Any]]:
    payload, headers, url = _build_openrouter_request(kwargs, stream=True)
    model = str(payload.get("model") or "")
    async with httpx.AsyncClient(timeout=kwargs.get("timeout") or 120) as client:
        async with client.stream("POST", url, headers=headers, json=payload) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                chunk = _parse_openrouter_sse_line(line, model)
                if chunk is _OPENROUTER_SSE_DONE:
                    break
                if chunk:
                    yield chunk


def _build_openrouter_request(
    kwargs: Mapping[str, Any],
    *,
    stream: bool,
) -> tuple[dict[str, Any], dict[str, str], str]:
    api_key = str(kwargs.get("api_key") or "")
    api_base = str(kwargs.get("api_base") or "https://openrouter.ai/api/v1").rstrip("/")
    model = _strip_litellm_prefix(str(kwargs.get("model") or ""))

    headers: dict[str, str] = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    extra_headers = kwargs.get("extra_headers") or {}
    if isinstance(extra_headers, Mapping):
        headers.update({str(k): str(v) for k, v in extra_headers.items() if v})

    payload: dict[str, Any] = {
        "model": model,
        "messages": kwargs.get("messages") or [],
        "stream": stream,
    }
    for key in (
        "temperature",
        "top_p",
        "max_tokens",
        "max_completion_tokens",
        "stop",
        "tools",
        "tool_choice",
        "parallel_tool_calls",
        "response_format",
    ):
        if kwargs.get(key) is not None:
            payload[key] = kwargs[key]

    stream_options = kwargs.get("stream_options")
    if stream and isinstance(stream_options, Mapping):
        payload["stream_options"] = dict(stream_options)

    extra_body = kwargs.get("extra_body")
    if isinstance(extra_body, Mapping):
        payload.update(dict(extra_body))

    return payload, headers, f"{api_base}/chat/completions"


def _strip_litellm_prefix(model: str) -> str:
    if model.startswith("openai/"):
        return model.split("/", 1)[1]
    if model.startswith("openrouter/"):
        return model.split("/", 1)[1]
    return model


def _normalize_openrouter_response(response: Mapping[str, Any]) -> dict[str, Any]:
    normalized = dict(response)
    choices = list(normalized.get("choices") or [])
    normalized["choices"] = choices
    for index, choice_value in enumerate(choices):
        choice = _as_dict(choice_value)
        message = _as_dict(choice.get("message", {}))
        reasoning_content = _extract_openrouter_reasoning(message)
        if reasoning_content:
            message["reasoning_content"] = reasoning_content
        choice["message"] = message
        choice.setdefault("index", index)
        choice.setdefault("finish_reason", choice.get("native_finish_reason") or "stop")
        choices[index] = choice
    normalized.setdefault("id", f"openrouter-{int(time.time() * 1000)}")
    normalized.setdefault("object", "chat.completion")
    normalized.setdefault("created", int(time.time()))
    return normalized


_OPENROUTER_SSE_DONE = object()


def _parse_openrouter_sse_line(
    line: str,
    fallback_model: str,
) -> dict[str, Any] | object | None:
    raw = line.strip()
    if not raw or raw.startswith(":"):
        return None

    if not raw.startswith("data:"):
        return None

    raw = raw.removeprefix("data:").strip()
    if raw == "[DONE]":
        return _OPENROUTER_SSE_DONE

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        logger.debug("Ignoring malformed OpenRouter SSE line: %r", raw[:200])
        return None

    if not isinstance(payload, Mapping):
        return None
    error = payload.get("error")
    if error:
        if isinstance(error, Mapping):
            message = error.get("message") or error.get("code") or str(error)
        else:
            message = str(error)
        raise ValueError(f"OpenRouter stream error: {message}")
    return _normalize_openrouter_stream_chunk(payload, fallback_model)


def _normalize_openrouter_stream_chunk(
    chunk: Mapping[str, Any],
    fallback_model: str,
) -> dict[str, Any]:
    normalized = dict(chunk)
    choices = list(normalized.get("choices") or [])
    normalized["choices"] = choices

    for index, choice_value in enumerate(choices):
        choice = _as_dict(choice_value)
        delta = _as_dict(choice.get("delta", {}))
        if not delta:
            delta = _as_dict(choice.get("message", {}))

        if "content" not in delta and choice.get("text") is not None:
            delta["content"] = choice.get("text")

        reasoning_content = _extract_openrouter_reasoning(delta)
        if not reasoning_content:
            reasoning_content = _extract_openrouter_reasoning(choice)
        if reasoning_content:
            delta["reasoning_content"] = reasoning_content

        choice["delta"] = delta
        choice.setdefault("index", index)
        if "finish_reason" not in choice:
            choice["finish_reason"] = choice.get("native_finish_reason")
        choices[index] = choice

    normalized.setdefault("id", f"openrouter-{int(time.time() * 1000)}")
    normalized.setdefault("object", "chat.completion.chunk")
    normalized.setdefault("created", int(time.time()))
    if fallback_model:
        normalized.setdefault("model", fallback_model)
    return normalized


def _log_openrouter_reasoning_response(
    mode: str,
    payload: Mapping[str, Any],
    response: Mapping[str, Any],
) -> None:
    choices = list(response.get("choices") or [])
    message = _as_dict(_as_dict(choices[0]).get("message", {})) if choices else {}
    reasoning_text = _extract_openrouter_reasoning(message)
    logger.debug(
        "OpenRouter raw reasoning response: mode=%s messages=%d stream=%s keys=%s reasoning_chars=%d content_type=%s",
        mode,
        len(payload.get("messages") or []),
        payload.get("stream"),
        sorted(message.keys()),
        len(reasoning_text),
        type(message.get("content")).__name__,
    )


def _extract_openrouter_reasoning(payload: Mapping[str, Any]) -> str:
    reasoning_content = payload.get("reasoning_content")
    if isinstance(reasoning_content, str) and reasoning_content.strip():
        return reasoning_content

    reasoning = payload.get("reasoning")
    if isinstance(reasoning, str) and reasoning.strip():
        return reasoning
    if reasoning and not isinstance(reasoning, str):
        return str(reasoning)

    details = payload.get("reasoning_details")
    if isinstance(details, list):
        parts: list[str] = []
        for item in details:
            item_dict = _as_dict(item)
            text = (
                item_dict.get("text")
                or item_dict.get("reasoning")
                or item_dict.get("content")
            )
            if isinstance(text, str) and text.strip():
                parts.append(text)
        return "".join(parts).strip()

    return ""


def _as_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if hasattr(value, "model_dump"):
        return value.model_dump()
    if isinstance(value, Mapping):
        return dict(value)
    return {}
