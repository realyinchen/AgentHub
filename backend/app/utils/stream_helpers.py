"""Agent execution helpers — model resolution, token extraction.

Shared by both ``/chat/invoke`` and ``/chat/stream`` code paths to eliminate
duplicated logic for model fallback and token accumulation.

For token + DAG persistence, use ``AgentExecutionService`` from ``app.services``.

Usage::

    from app.utils.stream_helpers import (
        resolve_model_name, empty_totals, extract_usage,
        accumulate_usage,
    )
    from app.services import AgentExecutionService

    model_name = resolve_model_name(user_input.model_name)
    totals = empty_totals()
    # ... run agent, iterate messages ...
    usage = extract_usage(msg)
    if usage:
        accumulate_usage(totals, usage)

    # Persist via service
    service = AgentExecutionService(agent)
    await service.persist(db=db, thread_id=thread_id, ...)
"""

from __future__ import annotations

import logging
from typing import Any

from app.infra.llm.model_manager import get_model_manager

logger = logging.getLogger(__name__)


# ── Token utilities ──────────────────────────────────────────────────────────


def empty_totals() -> dict[str, int]:
    """Return a zero-filled token totals dictionary."""
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


# ── Model resolution ─────────────────────────────────────────────────────────


def resolve_model_name(user_model: str | None) -> str | None:
    """Resolve a model name with default → first-active fallback chain.

    Args:
        user_model: Explicitly requested model name (may be *None* if the
            user hasn't selected a specific model from the frontend).

    Returns:
        The resolved model name, or *None* when **no** models are active
        in the system (caller should decide whether that is a hard error).
    """
    if user_model:
        return user_model
    manager = get_model_manager()
    return manager.get_default_llm_id() or manager.get_first_active_llm_id()


# Note: log_routing_decision removed — no longer needed since subagent routing was simplified.
# The agent now uses tools directly without structured routing decisions.


