"""Token usage extraction and accumulation helpers.

Shared by both the stream and invoke code paths so token-usage logic
stays in one place.

Usage:
    from app.utils.token_utils import extract_usage, accumulate_usage, empty_totals

    totals = empty_totals()
    usage = extract_usage(final_message)
    if usage:
        accumulate_usage(totals, usage)
    # totals now holds {input_tokens, cache_read, output_tokens, reasoning, total_tokens}
"""

from typing import Any


def empty_totals() -> dict[str, int]:
    """Return a zero-filled totals dictionary."""
    return {
        "input_tokens": 0,
        "cache_read": 0,
        "output_tokens": 0,
        "reasoning": 0,
        "total_tokens": 0,
    }


def extract_usage(final_message: Any) -> dict | None:
    """Extract token usage from a finalized AI message.

    Tries ``usage_metadata`` first (preferred), then falls back to
    ``response_metadata.token_usage``.

    Args:
        final_message: An ``AIMessage`` instance (or compatible object).

    Returns:
        A dict with keys ``input_tokens``, ``output_tokens``, ``total_tokens``,
        and optionally ``input_token_details`` / ``output_token_details``
        for cache-read and reasoning tokens.  ``None`` if no usage info is found.
    """
    if final_message is None:
        return None

    usage = getattr(final_message, "usage_metadata", None)
    if usage:
        return dict(usage)

    resp_meta = getattr(final_message, "response_metadata", None)
    if resp_meta and isinstance(resp_meta, dict):
        token_usage = resp_meta.get("token_usage")
        if token_usage:
            return {
                "input_tokens": token_usage.get("prompt_tokens", 0),
                "output_tokens": token_usage.get("completion_tokens", 0),
                "total_tokens": token_usage.get("total_tokens", 0),
            }
    return None


def accumulate_usage(totals: dict[str, int], usage: dict) -> None:
    """Accumulate per-call *usage* into running *totals* (mutated in-place)."""
    totals["input_tokens"] += usage.get("input_tokens", 0)
    totals["output_tokens"] += usage.get("output_tokens", 0)
    totals["total_tokens"] += usage.get("total_tokens", 0)

    input_details = usage.get("input_token_details")
    if isinstance(input_details, dict):
        totals["cache_read"] += input_details.get("cache_read", 0)

    output_details = usage.get("output_token_details")
    if isinstance(output_details, dict):
        totals["reasoning"] += output_details.get("reasoning", 0)