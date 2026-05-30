"""Agent execution helpers — model resolution, token extraction, DAG persistence.

Shared by both ``/chat/invoke`` and ``/chat/stream`` code paths to eliminate
duplicated logic for model fallback, token accumulation, and DAG snapshotting.

Usage (invoke path)::

    from app.utils.stream_helpers import (
        resolve_model_name, empty_totals, extract_usage,
        accumulate_usage, persist_tokens_and_dag,
    )

    model_name = resolve_model_name(user_input.model_name)
    totals = empty_totals()
    # ... run agent, iterate messages ...
    usage = extract_usage(msg)
    if usage:
        accumulate_usage(totals, usage)
    await persist_tokens_and_dag(db=db, agent=agent, ...)

Usage (stream path — inside AsyncWriteQueue callback)::

    async def _persist():
        database = get_database()
        async with database.session() as session:
            await persist_tokens_and_dag(
                db=session, agent=agent, thread_id=..., request_id=...,
                model_name=model_name, tokens=tokens,
            )
    write_queue.add("persist", _persist())
"""

from __future__ import annotations

import logging
from typing import Any, TYPE_CHECKING

from app.infra.llm.model_manager import get_model_manager

if TYPE_CHECKING:
    from uuid import UUID
    from sqlalchemy.ext.asyncio import AsyncSession

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


def log_routing_decision(sr: Any, *, prefix: str = "") -> None:
    """Log a structured routing decision for observability.

    Handles both Pydantic model and plain dict representations of
    ``RoutingDecision``.  Shared by invoke and stream code paths.

    Args:
        sr: The ``structured_response`` value from agent state (may be
            a Pydantic model, a dict, or *None*).
        prefix: Optional log message prefix (e.g. ``"Stream "``).
    """
    if sr is None:
        return
    logger.info(
        "%sStructured routing: action=%s target_agent=%s reasoning=%s",
        prefix,
        getattr(sr, "action", sr.get("action", "") if isinstance(sr, dict) else ""),
        getattr(sr, "target_agent", sr.get("target_agent", "") if isinstance(sr, dict) else ""),
        str(getattr(sr, "reasoning", sr.get("reasoning", "") if isinstance(sr, dict) else ""))[:200],
    )


async def persist_tokens_and_dag(
    db: AsyncSession,
    *,
    agent,  # CompiledStateGraph
    thread_id: UUID,
    request_id: str,
    model_name: str | None,
    tokens: dict[str, int],
) -> None:
    """Persist token usage + execution DAG after an agent response.

    Both operations are wrapped in try/except so that a failure in one
    (e.g. DAG construction) never prevents the other from completing.

    Args:
        db: An active async database session (not auto-committed inside
            this function — the caller owns transaction boundaries).
        agent: The compiled LangGraph agent used for DAG reconstruction.
        thread_id: Conversation thread identifier.
        request_id: Unique request identifier for this invocation.
        model_name: Resolved model name (or *None*).
        tokens: An ``empty_totals()``-shaped dict with
            ``input_tokens / cache_read / output_tokens / reasoning /
            total_tokens``.
    """
    from app.crud import chat as chat_crud
    from app.crud import trace as trace_crud
    from app.services import DagBuilder

    thread_id_str = str(thread_id)

    # ── Token persistence ────────────────────────────────────────────
    if tokens["total_tokens"] > 0:
        try:
            await chat_crud.update_conversation_tokens(
                db=db,
                thread_id=thread_id,
                input_tokens=tokens["input_tokens"],
                cache_read=tokens["cache_read"],
                output_tokens=tokens["output_tokens"],
                reasoning=tokens["reasoning"],
                total_tokens=tokens["total_tokens"],
            )
        except Exception:
            logger.exception("Failed to persist token usage for %s", request_id)

    # ── DAG persistence ──────────────────────────────────────────────
    try:
        dag_builder = DagBuilder(agent)
        dag = await dag_builder.get_execution_dag(thread_id_str)
        await trace_crud.upsert_trace(
            db=db,
            thread_id=thread_id,
            request_id=str(request_id),
            dag_data=dag.model_dump(),
            total_steps=len(dag.steps),
            model_name=model_name,
            input_tokens=tokens.get("input_tokens", 0),
            cache_read=tokens.get("cache_read", 0),
            output_tokens=tokens.get("output_tokens", 0),
            reasoning=tokens.get("reasoning", 0),
            total_tokens=tokens.get("total_tokens", 0),
        )
    except Exception:
        logger.exception("Failed to persist DAG for %s", request_id)