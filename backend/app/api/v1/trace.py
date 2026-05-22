"""API routes for Agent Trace Kanban Viewer."""

import asyncio
import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.dependencies import get_db
from app.crud import chat as chat_crud
from app.schemas.trace import (
    TraceListItem,
    TraceListResponse,
    StepOutput,
    ExecutionDag,
)
from app.observability import CheckpointReader, TraceBuilder, DagBuilder
from app.agents.registry import get_graph


logger = logging.getLogger(__name__)

api_router = APIRouter(prefix="/traces", tags=["traces"])


async def _get_step_count(agent, thread_id: str) -> int:
    """Resolve step count for a single thread via checkpoint reader.

    Uses the lighter ``get_checkpoint_history`` instead of the full
    ``get_execution_trace`` to avoid unnecessary message parsing.
    """
    try:
        reader = CheckpointReader(agent)
        checkpoints = await reader.get_checkpoint_history(thread_id)
        return len(checkpoints)
    except Exception:
        logger.debug("Failed to get step count for thread %s", thread_id)
        return 0


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
    db: AsyncSession = Depends(get_db),
):
    """List traces with pagination and time filtering.

    Returns TraceListResponse with pagination metadata.
    Default: first page, 10 items, last 24 hours.
    """
    try:
        convs, total = await chat_crud.list_traces(
            db, hours=hours, agent_id=agent_id, page=page, page_size=page_size
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

        # Resolve agents once — multiple conversations may share the same agent_id
        agent_cache: dict[str, object] = {}
        resolve_tasks: list[tuple] = []

        for conv in convs:
            aid = conv.agent_id or "default"
            agent = agent_cache.get(aid)
            if agent is None:
                agent = get_graph(aid)
                if agent is None:
                    continue  # inactive agent — skip
                agent_cache[aid] = agent
            resolve_tasks.append((conv, agent, str(conv.thread_id)))

        # Resolve step counts concurrently across all conversations
        if resolve_tasks:
            counts = await asyncio.gather(
                *(
                    _get_step_count(agent, thread_id)
                    for _, agent, thread_id in resolve_tasks
                ),
                return_exceptions=True,
            )
        else:
            counts = []

        # Build response items
        items: list[TraceListItem] = []
        for (conv, _agent, _tid), count in zip(resolve_tasks, counts):
            total_steps = count if isinstance(count, int) else 0
            items.append(
                TraceListItem(
                    thread_id=str(conv.thread_id),
                    title=conv.title or f"Conversation {conv.thread_id}",
                    total_steps=total_steps,
                    total_latency_ms=0,  # Latency not available in checkpointer
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


@api_router.get("/{thread_id}/steps", response_model=list[StepOutput])
async def get_trace_steps(thread_id: UUID, agent_id: str = Query("default")):
    """Get all execution steps for a specific thread.

    Returns a list of StepOutput objects representing each step in the execution.
    This replaces the old message_steps-based approach by reading directly from
    LangGraph checkpointer.
    """
    try:
        agent = get_graph(agent_id)
        if agent is None:
            raise HTTPException(
                status_code=404, detail=f"Agent '{agent_id}' not found or not active"
            )
        trace_reader = TraceBuilder(agent)
        steps = await trace_reader.get_execution_trace(str(thread_id))

        if not steps:
            raise HTTPException(
                status_code=404, detail="No execution steps found for this thread"
            )

        return steps

    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            f"Error getting trace steps for thread {thread_id}: {e}", exc_info=True
        )
        raise HTTPException(status_code=500, detail=str(e))


@api_router.get("/{thread_id}/dag", response_model=ExecutionDag)
async def get_trace_dag(thread_id: UUID, agent_id: str = Query("default")):
    """Get the execution DAG for a specific thread.

    Returns the full execution DAG with nodes and edges, suitable for visualization.
    Each node contains step details and metadata.
    """
    try:
        agent = get_graph(agent_id)
        if agent is None:
            raise HTTPException(
                status_code=404, detail=f"Agent '{agent_id}' not found or not active"
            )
        trace_reader = DagBuilder(agent)
        dag = await trace_reader.get_execution_dag(str(thread_id))

        if not dag.nodes:
            raise HTTPException(
                status_code=404, detail="No execution DAG found for this thread"
            )

        return dag

    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            f"Error getting trace DAG for thread {thread_id}: {e}", exc_info=True
        )
        raise HTTPException(status_code=500, detail=str(e))


@api_router.get("/{thread_id}/steps/{step_number}", response_model=StepOutput)
async def get_trace_step_by_number(
    thread_id: UUID, step_number: int, agent_id: str = Query("default")
):
    """Get a specific step by number.

    Returns detailed information for a specific step in the execution.
    """
    try:
        agent = get_graph(agent_id)
        if agent is None:
            raise HTTPException(
                status_code=404, detail=f"Agent '{agent_id}' not found or not active"
            )
        trace_reader = TraceBuilder(agent)
        step = await trace_reader.get_step_by_number(str(thread_id), step_number)

        if not step:
            raise HTTPException(status_code=404, detail="Step not found")

        return step

    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            f"Error getting step {step_number} for thread {thread_id}: {e}",
            exc_info=True,
        )
        raise HTTPException(status_code=500, detail=str(e))


@api_router.get("/{thread_id}/checkpoints/{checkpoint_id}", response_model=StepOutput)
async def get_trace_step_by_checkpoint(
    thread_id: UUID, checkpoint_id: str, agent_id: str = Query("default")
):
    """Get a specific step by checkpoint ID.

    Returns detailed information for a step using its checkpoint ID.
    """
    try:
        agent = get_graph(agent_id)
        if agent is None:
            raise HTTPException(
                status_code=404, detail=f"Agent '{agent_id}' not found or not active"
            )
        trace_reader = TraceBuilder(agent)
        step = await trace_reader.get_step_at_checkpoint(str(thread_id), checkpoint_id)

        if not step:
            raise HTTPException(status_code=404, detail="Checkpoint not found")

        return step

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
    agent_id: str = Query("default"),
):
    """Replay a trace from a specific step range.

    Returns steps in the specified range for replay functionality.
    """
    try:
        agent = get_graph(agent_id)
        if agent is None:
            raise HTTPException(
                status_code=404, detail=f"Agent '{agent_id}' not found or not active"
            )
        trace_reader = TraceBuilder(agent)
        steps = await trace_reader.replay_steps(str(thread_id), from_step, to_step)

        if not steps:
            raise HTTPException(
                status_code=404, detail="No steps found in the specified range"
            )

        return steps

    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            f"Error replaying trace for thread {thread_id}: {e}", exc_info=True
        )
        raise HTTPException(status_code=500, detail=str(e))
