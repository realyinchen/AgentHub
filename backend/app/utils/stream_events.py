"""Reusable Server-Sent Event helpers for streaming APIs.

This module intentionally contains only pure formatting/content helpers. It has
no FastAPI, database, Agent registry, or LangGraph runtime dependencies, so it
can be reused by streaming routes and error formatters without coupling them.
"""

from __future__ import annotations

import json
from typing import Any


def sse(data: Any) -> str:
    """Format data as a Server-Sent Event message."""
    return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"


def sse_error(content: str, error_type: str = "error") -> str:
    """Format an error as a Server-Sent Event message.

    Keep the existing backend SSE error payload unchanged for PR-J:

    {
        "type": "error",
        "content": content,
        "error_type": error_type,
    }

    The future SSE protocol normalization task is tracked in backend/TODO.md.
    """
    return sse({"type": "error", "content": content, "error_type": error_type})


def has_meaningful_content(output: Any) -> bool:
    """Return whether a LangChain message output contains user-visible text."""
    if output is None:
        return False

    content = getattr(output, "content", "")
    if isinstance(content, str):
        return bool(content.strip())

    if isinstance(content, list):
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                if block.get("text", "").strip():
                    return True

    return False