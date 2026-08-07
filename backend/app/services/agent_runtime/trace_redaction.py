from __future__ import annotations

import re
from typing import Any


_FORBIDDEN_KEYS = frozenset(
    {
        "access_token",
        "action_id",
        "api_key",
        "authorization",
        "credentials",
        "database",
        "model_id",
        "model_name",
        "password",
        "plan_id",
        "provider_name",
        "refresh_token",
        "request_id",
        "secret",
        "secret_key",
        "thread_id",
        "token",
        "user_id",
    }
)
_CREDENTIAL_TEXT_RE = re.compile(
    r"(?:\bsk-[a-z0-9_-]{12,}\b|"
    r"\bbearer\s+[a-z0-9._~+/=-]{12,}|"
    r"\b(?:api[_ -]?key|password|secret|token)\s*[:=]\s*\S{6,})",
    re.IGNORECASE,
)
_MAX_STRING = 300
_MAX_ITEMS = 20


def redact_tool_args(arguments: dict[str, Any]) -> dict[str, Any]:
    """Return observable tool arguments with credentials and system fields removed."""

    if not isinstance(arguments, dict):
        return {}
    return {
        str(key): _redact_value(str(key), value)
        for key, value in arguments.items()
        if str(key).strip().lower() not in _FORBIDDEN_KEYS
    }


def _redact_value(key: str, value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(child_key): _redact_value(str(child_key), child)
            for child_key, child in value.items()
            if str(child_key).strip().lower() not in _FORBIDDEN_KEYS
        }
    if isinstance(value, list):
        return [_redact_value(key, item) for item in value][:_MAX_ITEMS]
    if isinstance(value, str):
        if _CREDENTIAL_TEXT_RE.search(value):
            return "[redacted]"
        return value[:_MAX_STRING]
    return value


__all__ = ["redact_tool_args"]
