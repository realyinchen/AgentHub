"""Shared post-processing for agent invoke / stream code paths.

Extracted from ``api/v1/chat.py`` and ``api/v1/stream.py`` to eliminate
~80 lines of duplicated model-fallback + token-persist + DAG-persist logic.

Usage (invoke path — synchronous with FastAPI db session)::

    from app.utils.stream_helpers import resolve_model_name, persist_tokens_and_dag

    model_name = resolve_model_name(user_input.model_name)
    # ... run agent ...
    await persist_tokens_and_dag(
        db=db, agent=agent, thread_id=..., agent_id=..., request_id=...,
        model_name=model_name, tokens=totals,
    )

Usage (stream path — inside AsyncWriteQueue callback)::

    async def _persist():
        database = get_database()
        async with database.session() as session:
            await persist_tokens_and_dag(
                db=session, agent=agent, thread_id=..., agent_id=...,
                request_id=..., model_name=model_name, tokens=tokens,
            )
    write_queue.add("persist", _persist())
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from app.infra.llm.model_manager import get_model_manager

if TYPE_CHECKING:
    from uuid import UUID
    from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


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
    return (
        manager.get_default_llm_id()
        or manager.get_first_active_llm_id()
    )


async def persist_tokens_and_dag(
    db: AsyncSession,
    *,
    agent,              # CompiledStateGraph
    thread_id: UUID,
    agent_id: str,
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
        agent_id: Agent identifier string (e.g. ``"chatbot"``).
        request_id: Unique request identifier for this invocation.
        model_name: Resolved model name (or *None*).
        tokens: An ``empty_totals()``-shaped dict with
            ``input_tokens / cache_read / output_tokens / reasoning /
            total_tokens``.
    """
    from app.crud import chat as chat_crud
    from app.crud import trace as trace_crud
    from app.observability import DagBuilder

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
            agent_id=agent_id,
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