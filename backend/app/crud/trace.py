"""CRUD operations for TraceExecution — persisted DAG snapshots.

Read paths return (dag_data, steps, total_steps) tuples for direct
deserialization in trace endpoints. Write paths are used by stream/invoke
to persist DAG at completion time.
"""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.trace import TraceExecution


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


async def get_latest_trace_info(
    db: AsyncSession, thread_id: UUID
) -> tuple[str | None, str | None]:
    """Return (agent_id, model_name) from the most recent trace in a thread.

    Used when entering a historical conversation to determine which agent
    and LLM model were last used. The caller should validate the model
    against the active models table and fall back to the default if the
    model is no longer active.

    Returns:
        Tuple of (agent_id, model_name). Both are None if no trace exists.
    """
    stmt = (
        select(
            TraceExecution.agent_id,
            TraceExecution.model_name,
        )
        .where(TraceExecution.thread_id == thread_id)
        .order_by(TraceExecution.created_at.desc())
        .limit(1)
    )
    result = await db.execute(stmt)
    row = result.one_or_none()
    if row is None:
        return None, None
    return row.agent_id, row.model_name


async def upsert_trace(
    db: AsyncSession,
    thread_id: UUID,
    agent_id: str,
    request_id: str,
    dag_data: dict,
    total_steps: int,
    model_name: str | None = None,
    input_tokens: int = 0,
    cache_read: int = 0,
    output_tokens: int = 0,
    reasoning: int = 0,
    total_tokens: int = 0,
) -> TraceExecution:
    """Insert or update a trace execution for the given request_id.

    Uses request_id as the business key — overwrites any previous entry
    for the same request to support idempotent retries.

    Args:
        db: Database session.
        thread_id: Parent conversation thread.
        agent_id: Agent type used for this turn.
        request_id: Unique request identifier (business key).
        dag_data: Complete ExecutionDag as a dict.
        total_steps: Number of steps in the DAG.
        model_name: LLM model name used for this turn.
        input_tokens: Per-request input tokens.
        cache_read: Per-request cache read tokens.
        output_tokens: Per-request output tokens.
        reasoning: Per-request reasoning tokens.
        total_tokens: Per-request total tokens.
    """
    stmt = select(TraceExecution).where(
        TraceExecution.request_id == request_id,
    )
    result = await db.execute(stmt)
    existing = result.scalar_one_or_none()

    if existing is not None:
        existing.dag_data = dag_data
        existing.total_steps = total_steps
        existing.agent_id = agent_id
        existing.model_name = model_name
        existing.input_tokens = input_tokens
        existing.cache_read = cache_read
        existing.output_tokens = output_tokens
        existing.reasoning = reasoning
        existing.total_tokens = total_tokens
        await db.flush()
        return existing

    row = TraceExecution(
        thread_id=thread_id,
        agent_id=agent_id,
        request_id=request_id,
        dag_data=dag_data,
        total_steps=total_steps,
        model_name=model_name,
        input_tokens=input_tokens,
        cache_read=cache_read,
        output_tokens=output_tokens,
        reasoning=reasoning,
        total_tokens=total_tokens,
    )
    db.add(row)
    await db.flush()
    return row