from __future__ import annotations

from typing import Any

from app.schemas.chat import ChatMessage, UserInput


_SAFE_RUNTIME_TRACE_FIELDS = frozenset(
    {
        "plan_id",
        "route_type",
        "intent",
        "planner_used",
        "plan_source",
        "receipt_status",
        "duration_ms",
    }
)
_SAFE_TOOL_INFO_FIELDS = frozenset(
    {
        "name",
        "id",
        "order",
        "status",
        "duration_ms",
        "system_executed",
        "plan_id",
        "depends_on",
    }
)
_SAFE_USER_CUSTOM_FIELDS = frozenset(
    {
        "quoted_message_id",
        "user_content",
    }
)


def user_event_metadata(user_input: UserInput) -> dict[str, Any]:
    """Keep user-visible quote metadata; discard runtime routing context."""

    custom = user_input.custom_data or {}
    safe = {
        key: custom[key]
        for key in _SAFE_USER_CUSTOM_FIELDS
        if key in custom
    }
    return {"custom_data": safe} if safe else {}


def assistant_event_metadata(message: ChatMessage) -> dict[str, Any]:
    """Persist display metadata without reasoning, tool payloads, or secrets."""

    custom = message.custom_data or {}
    safe_custom: dict[str, Any] = {}
    runtime_trace = custom.get("runtime_trace")
    if isinstance(runtime_trace, dict):
        safe_custom["runtime_trace"] = {
            key: runtime_trace[key]
            for key in _SAFE_RUNTIME_TRACE_FIELDS
            if key in runtime_trace
        }
    tool_info = custom.get("tool_info")
    if isinstance(tool_info, list):
        safe_custom["tool_info"] = [
            {
                key: item[key]
                for key in _SAFE_TOOL_INFO_FIELDS
                if key in item
            }
            for item in tool_info
            if isinstance(item, dict)
        ]
    return {
        "chat_message": {
            "response_metadata": _safe_response_metadata(
                message.response_metadata,
            ),
            "custom_data": safe_custom,
        }
    }


def receipt_references(message: ChatMessage) -> list[str]:
    """Extract only completed action identifiers from a validated receipt."""

    explicit = (message.custom_data or {}).get("receipt_refs")
    if isinstance(explicit, list):
        refs = [
            str(item).strip()
            for item in explicit
            if str(item).strip()
        ][:64]
        if refs:
            return list(dict.fromkeys(refs))
    receipt = (message.custom_data or {}).get("plan_receipt")
    if not isinstance(receipt, dict):
        return []
    actions = receipt.get("actions")
    if not isinstance(actions, list):
        return []
    return [
        str(item.get("action_id"))
        for item in actions
        if isinstance(item, dict)
        and item.get("status") == "completed"
        and str(item.get("action_id") or "").strip()
    ][:64]


def _safe_response_metadata(value: dict[str, Any]) -> dict[str, Any]:
    safe: dict[str, Any] = {}
    for key in ("finish_reason", "model_name", "model_provider"):
        item = value.get(key)
        if isinstance(item, (str, int, float, bool)) or item is None:
            if key in value:
                safe[key] = item
    for key in ("usage", "token_usage"):
        item = value.get(key)
        if not isinstance(item, dict):
            continue
        safe[key] = {
            child_key: child_value
            for child_key, child_value in item.items()
            if child_key
            in {
                "input_tokens",
                "output_tokens",
                "total_tokens",
                "prompt_tokens",
                "completion_tokens",
            }
            and isinstance(child_value, int)
        }
    return safe
