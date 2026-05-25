"""API routes for Agent Trace Kanban Viewer.

All endpoints read from the persisted ``trace_executions`` table, so trace
viewing never depends on agent graph compilation or agent liveness.
"""

import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.dependencies import get_db
from app.crud import chat as chat_crud
from app.crud import trace as trace_crud
from app.models.trace import TraceExecution
from app.schemas.trace import (
    TraceListItem,
    TraceListResponse,
    StepOutput,
    ExecutionDag,
)

logger = logging.getLogger(__name__)

api_router = APIRouter(prefix="/traces", tags=["traces"])


# ── helpers ──────────────────────────────────────────────────────────────────


async def _resolve_agent_id(
    db: AsyncSession, agent_id: str, thread_id: UUID, user_id: str
) -> tuple[str | None, int | None, str | None]:
    """Resolve agent_id when "all" from the conversation table.

    Returns:
        (agent_id, status_code, error_detail).  When successful status_code
        and error are None.
    """
    if agent_id != "all":
        return agent_id, None, None

    conv = await chat_crud.read_conversation_by_thread_id(
        db, thread_id, user_id=user_id
    )
    if conv is None or not conv.agent_id:
        return None, 404, f"No conversation found for thread {thread_id}"
    return conv.agent_id, None, None


async def _verify_trace_owner(
    db: AsyncSession,
    thread_id: UUID,
    user_id: str,
) -> None:
    """Verify that a thread belongs to user_id, or raise 404."""
    conv = await chat_crud.read_conversation_by_thread_id(
        db=db, thread_id=thread_id, user_id=user_id,
    )
    if conv is None:
        raise HTTPException(status_code=404, detail="Conversation not found")


# ── routes ───────────────────────────────────────────────────────────────────


@api_router.get("", response_model=TraceListResponse)
async def list_traces(
    page: int = Query(0, ge=0, description="Page number (0-indexed)"),
    page_size: int = Query(10, ge=1, le=100, description="Number of traces per page"),
    hours: int = Query(
        24,
        ge=1,
        le=168,
        description="Filter by hours back from now (max 168 hours / 7 days)",
    ),
    agent_id: str = Query("all", description="Agent ID to filter traces"),
    user_id: str = Query(..., description="User ID to scope traces"),
    db: AsyncSession = Depends(get_db),
):
    """List traces with pagination and time filtering.

    Returns TraceListResponse with pagination metadata.
    Default: first page, 10 items, last 24 hours.

    Step counts come from the persisted ``trace_executions`` table rather
    than live checkpointer queries — no graph compilation needed.
    """
    try:
        convs, total = await chat_crud.list_traces(
            db,
            hours=hours,
            agent_id=agent_id,
            page=page,
            page_size=page_size,
            user_id=user_id,
        )

        total_pages = (total + page_size - 1) // page_size if total > 0 else 0
        has_more = (page + 1) * page_size < total

        if not convs:
            return TraceListResponse(
                items=[],
                total=total,
                total_pages=total_pages,
                page=page,
                page_size=page_size,
                has_more=False,
                filter_hours=hours,
            )

        # Batch-fetch latest step counts from persisted trace_executions
        thread_ids = [conv.thread_id for conv in convs]
        step_counts = await _batch_fetch_step_counts(db, thread_ids)

        items: list[TraceListItem] = []
        for conv in convs:
            items.append(
                TraceListItem(
                    thread_id=str(conv.thread_id),
                    title=conv.title or f"Conversation {conv.thread_id}",
                    total_steps=step_counts.get(conv.thread_id, 0),
                    total_latency_ms=0,
                    last_updated=conv.updated_at,
                    agent_id=conv.agent_id,
                )
            )

        return TraceListResponse(
            items=items,
            total=total,
            total_pages=total_pages,
            page=page,
            page_size=page_size,
            has_more=has_more,
            filter_hours=hours,
        )
    except Exception as e:
        logger.error(f"Error listing traces: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


async def _batch_fetch_step_counts(
    db: AsyncSession, thread_ids: list[UUID]
) -> dict[UUID, int]:
    """Return {thread_id: total_steps} using DISTINCT ON for latest per thread."""
    if not thread_ids:
        return {}

    sub = (
        select(
            TraceExecution.thread_id,
            TraceExecution.total_steps,
        )
        .where(TraceExecution.thread_id.in_(thread_ids))
        .order_by(TraceExecution.thread_id, TraceExecution.created_at.desc())
    )

    rows = (await db.execute(sub)).all()
    result: dict[UUID, int] = {}
    for tid, steps in rows:
        if tid not in result:
            result[tid] = steps
    return result


@api_router.get("/{thread_id}/steps", response_model=list[StepOutput])
async def get_trace_steps(
    thread_id: UUID,
    agent_id: str = Query("all"),
    user_id: str = Query(..., description="User ID to verify ownership"),
    db: AsyncSession = Depends(get_db),
):
    """Get all execution steps for a specific thread from persisted DAG.

    Reads from ``trace_executions`` — no graph compilation required.
    Agent_id="all" resolves from the conversation table automatically.
    """
    try:
        agent_id_resolved, status_code, error = await _resolve_agent_id(
            db, agent_id, thread_id, user_id
        )
        if agent_id_resolved is None:
            raise HTTPException(status_code=status_code or 404, detail=error)

        _, steps, _ = await trace_crud.get_latest_dag_and_steps(db, thread_id)
        if not steps:
            raise HTTPException(
                status_code=404, detail="No execution steps found for this thread"
            )

        return [StepOutput(**s) for s in steps]

    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            f"Error getting trace steps for thread {thread_id}: {e}", exc_info=True
        )
        raise HTTPException(status_code=500, detail=str(e))


@api_router.get("/{thread_id}/dag", response_model=ExecutionDag)
async def get_trace_dag(
    thread_id: UUID,
    agent_id: str = Query("all"),
    user_id: str = Query(..., description="User ID to verify ownership"),
    db: AsyncSession = Depends(get_db),
):
    """Get the execution DAG for a specific thread from persisted data.

    Reads from ``trace_executions`` table — no graph compilation required.
    Returns the full execution DAG with nodes and edges for visualization.
    """
    try:
        agent_id_resolved, status_code, error = await _resolve_agent_id(
            db, agent_id, thread_id, user_id
        )
        if agent_id_resolved is None:
            raise HTTPException(status_code=status_code or 404, detail=error)

        dag_data, _, _ = await trace_crud.get_latest_dag_and_steps(db, thread_id)
        if dag_data is None:
            raise HTTPException(
                status_code=404, detail="No execution DAG found for this thread"
            )

        return ExecutionDag(**dag_data)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            f"Error getting trace DAG for thread {thread_id}: {e}", exc_info=True
        )
        raise HTTPException(status_code=500, detail=str(e))


@api_router.get("/{thread_id}/steps/{step_number}", response_model=StepOutput)
async def get_trace_step_by_number(
    thread_id: UUID,
    step_number: int,
    agent_id: str = Query("all"),
    user_id: str = Query(..., description="User ID to verify ownership"),
    db: AsyncSession = Depends(get_db),
):
    """Get a specific step by number from persisted DAG.

    Reads from ``trace_executions`` — no graph compilation required.
    """
    try:
        await _verify_trace_owner(db, thread_id, user_id)
        _, steps, _ = await trace_crud.get_latest_dag_and_steps(db, thread_id)
        if not steps:
            raise HTTPException(
                status_code=404, detail="No execution steps found for this thread"
            )

        for s in steps:
            if s.get("step_number") == step_number:
                return StepOutput(**s)

        raise HTTPException(status_code=404, detail="Step not found")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            f"Error getting step {step_number} for thread {thread_id}: {e}",
            exc_info=True,
        )
        raise HTTPException(status_code=500, detail=str(e))


@api_router.get(
    "/{thread_id}/checkpoints/{checkpoint_id}", response_model=StepOutput
)
async def get_trace_step_by_checkpoint(
    thread_id: UUID,
    checkpoint_id: str,
    agent_id: str = Query("all"),
    user_id: str = Query(..., description="User ID to verify ownership"),
    db: AsyncSession = Depends(get_db),
):
    """Get a specific step by checkpoint ID from persisted DAG.

    Reads from ``trace_executions`` — no graph compilation required.
    """
    try:
        await _verify_trace_owner(db, thread_id, user_id)
        _, steps, _ = await trace_crud.get_latest_dag_and_steps(db, thread_id)
        if not steps:
            raise HTTPException(
                status_code=404, detail="No execution steps found for this thread"
            )

        for s in steps:
            if s.get("checkpoint_id") == checkpoint_id:
                return StepOutput(**s)

        raise HTTPException(status_code=404, detail="Checkpoint not found")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            f"Error getting checkpoint {checkpoint_id} for thread {thread_id}: {e}",
            exc_info=True,
        )
        raise HTTPException(status_code=500, detail=str(e))


@api_router.get("/{thread_id}/replay", response_model=list[StepOutput])
async def replay_trace(
    thread_id: UUID,
    from_step: int = Query(1, ge=1, description="Start from this step number"),
    to_step: int | None = Query(None, ge=1, description="End at this step number"),
    agent_id: str = Query("all"),
    user_id: str = Query(..., description="User ID to verify ownership"),
    db: AsyncSession = Depends(get_db),
):
    """Replay a trace from a specific step range from persisted DAG.

    Reads from ``trace_executions`` — no graph compilation required.
    """
    try:
        await _verify_trace_owner(db, thread_id, user_id)
        _, steps, _ = await trace_crud.get_latest_dag_and_steps(db, thread_id)
        if not steps:
            raise HTTPException(
                status_code=404, detail="No execution steps found for this thread"
            )

        result = steps[from_step - 1 : to_step]
        if not result:
            raise HTTPException(
                status_code=404, detail="No steps found in the specified range"
            )

        return [StepOutput(**s) for s in result]

    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            f"Error replaying trace for thread {thread_id}: {e}", exc_info=True
        )
        raise HTTPException(status_code=500, detail=str(e))