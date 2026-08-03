from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage

from app.infra.llm.factory import create_llm_from_config
from app.services.model_probe.contracts import ProbeConfig, ProbeOutcome
from app.services.model_probe.errors import classify_probe_error, safe_probe_error
from app.utils.message import convert_message_content_to_string, extract_thinking


BASIC_PROMPT = "Reply with exactly: OK"
THINKING_PROMPT = (
    "Use your reasoning mode if it is available. Decide whether 17 + 25 = 42. "
    "Final answer must be exactly: OK"
)
ChatInvoker = Callable[..., Awaitable[AIMessage]]


class ChatProbe:
    """Probe chat generation and optional reasoning capabilities."""

    probe_kind = "chat"

    def __init__(self, invoker: ChatInvoker | None = None) -> None:
        self._invoker = invoker or _invoke_chat

    async def run(self, config: ProbeConfig) -> ProbeOutcome:
        outcome = ProbeOutcome(probe_kind=self.probe_kind, probe_ok=False)
        try:
            basic_response = await self._invoker(
                config=config,
                thinking_mode=config.configured_thinking,
                prompt=BASIC_PROMPT,
            )
            basic_content = convert_message_content_to_string(basic_response.content)
            outcome.probe_ok = bool(basic_content.strip())
            outcome.summary.update(
                {
                    "chat_content_chars": len(basic_content),
                    "chat_response_metadata_keys": sorted(
                        basic_response.response_metadata.keys()
                    ),
                }
            )
            if not outcome.probe_ok:
                outcome.error_category = "provider"
                outcome.error_type = "empty_chat_response"
                outcome.last_error = "Model returned an empty basic chat response."
                return outcome
        except Exception as exc:
            outcome.error_category = classify_probe_error(exc)
            outcome.error_type = "chat_request_failed"
            outcome.last_error = safe_probe_error(exc)
            return outcome

        if not config.check_thinking:
            return outcome

        try:
            thinking_response = await self._invoker(
                config=config,
                thinking_mode=True,
                prompt=THINKING_PROMPT,
            )
            thinking_text, field_path = _detect_thinking(thinking_response)
            thinking_content = convert_message_content_to_string(
                thinking_response.content
            )
            outcome.thinking_request_ok = True
            outcome.reasoning_text_ok = bool(thinking_text)
            outcome.reasoning_field_path = field_path
            outcome.summary.update(
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
            outcome.thinking_request_ok = False
            outcome.reasoning_text_ok = False
            outcome.error_category = classify_probe_error(exc)
            outcome.error_type = "thinking_request_failed"
            outcome.last_error = safe_probe_error(exc)

        return outcome


async def _invoke_chat(
    *,
    config: ProbeConfig,
    thinking_mode: bool,
    prompt: str,
) -> AIMessage:
    llm = create_llm_from_config(
        provider=config.provider,
        model_id=config.provider_model_id,
        api_key=config.api_key,
        base_url=config.base_url,
        is_openai_compatible=config.is_openai_compatible,
        thinking_mode=thinking_mode,
        extra_headers=config.extra_headers,
    )
    response = await asyncio.wait_for(
        llm.ainvoke([HumanMessage(content=prompt)]),
        timeout=config.timeout_seconds,
    )
    if not isinstance(response, AIMessage):
        raise TypeError(f"Expected AIMessage, got {type(response).__name__}")
    return response


def _detect_thinking(message: AIMessage) -> tuple[str, str | None]:
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


__all__ = ["ChatProbe"]
