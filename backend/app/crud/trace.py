"""CRUD operations for TraceExecution — persisted DAG snapshots.

Read paths return (dag_data, steps, total_steps) tuples for direct
deserialization in trace endpoints. Write paths are used by stream/invoke
to persist DAG at completion time.

Persistence Function:
    ``persist_agent_trace`` — Token + DAG persistence after agent response.
"""

import logging
from typing import Any
from uuid import UUID

from langgraph.graph.state import CompiledStateGraph


from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.crud import chat as chat_crud
from app.models.trace import TraceExecution
from app.services.agent_runtime.execution_graph import ExecutionGraph
from app.utils.dag import DagBuilder


logger = logging.getLogger(__name__)


async def get_latest_dag_and_steps(
    db: AsyncSession, thread_id: UUID
) -> tuple[dict | None, list | None, int | None]:
    """Return the DAG data for the most recent turn in a thread.

    Returns:
        Tuple of (dag_data dict, steps list, total_steps int) or
        (None, None, None) if no execution has been recorded.
    """
    stmt = (
        select(
            TraceExecution.dag_data,
            TraceExecution.total_steps,
        )
        .where(TraceExecution.thread_id == thread_id)
        .order_by(TraceExecution.created_at.desc())
        .limit(1)
    )
    result = await db.execute(stmt)
    row = result.one_or_none()
    if row is None:
        return None, None, None
    dag = row.dag_data
    return dag, dag.get("steps", []), row.total_steps


async def get_dag_by_request_id(db: AsyncSession, request_id: str) -> dict | None:
    """Return the DAG data for a specific request_id.

    Args:
        db: Database session.
        request_id: Unique request identifier (business key).

    Returns:
        DAG data dict, or None if no trace exists for this request_id.
    """
    stmt = select(TraceExecution.dag_data).where(
        TraceExecution.request_id == request_id,
    )
    result = await db.execute(stmt)
    row = result.one_or_none()
    if row is None:
        return None
    return row.dag_data


async def get_traces_by_thread(
    db: AsyncSession, thread_id: UUID
) -> list[tuple[str, str]]:
    """Return all traces for a thread, ordered by creation time.

    Returns:
        List of (request_id, created_at) tuples in chronological order.
    """
    stmt = (
        select(TraceExecution.request_id, TraceExecution.created_at)
        .where(TraceExecution.thread_id == thread_id)
        .order_by(TraceExecution.created_at.asc())
    )
    result = await db.execute(stmt)
    rows = result.all()
    return [(row.request_id, str(row.created_at)) for row in rows]


async def get_latest_model_name(db: AsyncSession, thread_id: UUID) -> str | None:
    """Return the model_name from the most recent trace in a thread.

    Used when entering a historical conversation to determine which LLM model
    was last used. The caller should validate the model against the active
    models table and fall back to the default if the model is no longer active.

    Returns:
        Model name string, or None if no trace exists.
    """
    stmt = (
        select(TraceExecution.model_name)
        .where(TraceExecution.thread_id == thread_id)
        .order_by(TraceExecution.created_at.desc())
        .limit(1)
    )
    result = await db.execute(stmt)
    row = result.one_or_none()
    if row is None:
        return None
    return row.model_name


async def upsert_trace(
    db: AsyncSession,
    thread_id: UUID,
    request_id: str,
    dag_data: dict,
    total_steps: int,
    model_name: str | None = None,
) -> TraceExecution:
    """Insert or update a trace execution for the given request_id.

    Uses request_id as the business key — overwrites any previous entry
    for the same request to support idempotent retries.

    Args:
        db: Database session.
        thread_id: Parent conversation thread.
        request_id: Unique request identifier (business key).
        dag_data: Complete ExecutionDag as a dict.
        total_steps: Number of steps in the DAG.
        model_name: LLM model name used for this turn.
    """
    stmt = select(TraceExecution).where(
        TraceExecution.request_id == request_id,
    )
    result = await db.execute(stmt)
    existing = result.scalar_one_or_none()

    if existing is not None:
        existing.dag_data = dag_data
        existing.total_steps = total_steps
        existing.model_name = model_name
        await db.flush()
        return existing

    row = TraceExecution(
        thread_id=thread_id,
        request_id=request_id,
        dag_data=dag_data,
        total_steps=total_steps,
        model_name=model_name,
    )
    db.add(row)
    await db.flush()
    return row


async def persist_agent_trace(
    db: AsyncSession,
    agent: CompiledStateGraph,
    *,
    thread_id: UUID,
    request_id: str,
    model_name: str | None,
    tokens: dict[str, int],
    before_checkpoint_id: str | None = None,
    before_message_count: int = 0,
    reasoning_segments: dict[str, str] | None = None,
    system_tool_steps: list[dict[str, Any]] | None = None,
    system_execution_graph: ExecutionGraph | dict[str, Any] | None = None,
) -> None:
    """Persist token usage and execution DAG after an agent response.

    Unified persistence function that handles:
    1. Token usage update to conversations table
    2. DAG snapshot upsert to trace_executions table

    Both operations are wrapped in independent try/except blocks so that
    a failure in one (e.g. DAG construction) never prevents the other
    from completing.

    Args:
        db: An active async database session (not auto-committed inside
            this function — the caller owns transaction boundaries).
        agent: A compiled LangGraph agent used for DAG reconstruction.
        thread_id: Conversation thread identifier.
        request_id: Unique request identifier for this invocation.
        model_name: Resolved model name (or None).
        tokens: A dict with keys: input_tokens, output_tokens,
            total_tokens.
        before_checkpoint_id: Checkpoint ID before this turn started.
            Used to filter checkpoint history for per-turn DAG construction.
        before_message_count: Number of messages before this turn started.
            Used as fallback when checkpoint history is unavailable.
        reasoning_segments: Dict mapping AIMessage.id to reasoning content.
            Used to inject thinking into each AI node in the DAG when
            checkpointer doesn't preserve reasoning content.
    """

    thread_id_str = str(thread_id)

    # Token persistence - update conversations table
    if tokens["total_tokens"] > 0:
        try:
            await chat_crud.update_conversation_tokens(
                db=db,
                thread_id=thread_id,
                input_tokens=tokens["input_tokens"],
                output_tokens=tokens["output_tokens"],
                total_tokens=tokens["total_tokens"],
            )
        except Exception:
            logger.exception("Failed to persist token usage for %s", request_id)

    # DAG persistence
    try:
        dag_builder = DagBuilder(agent)
        dag = await dag_builder.get_execution_dag(
            thread_id_str,
            before_checkpoint_id=before_checkpoint_id,
            before_message_count=before_message_count,
            reasoning_segments=reasoning_segments,
            system_tool_steps=system_tool_steps,
        )
        if system_execution_graph is not None:
            dag.execution_graph = ExecutionGraph.model_validate(
                system_execution_graph
            )
        await upsert_trace(
            db=db,
            thread_id=thread_id,
            request_id=str(request_id),
            dag_data=dag.model_dump(),
            total_steps=len(dag.steps),
            model_name=model_name,
        )
    except Exception:
        logger.exception("Failed to persist DAG for %s", request_id)
