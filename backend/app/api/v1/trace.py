"""API routes for Agent Trace Kanban Viewer."""

import logging
from datetime import datetime, timedelta, timezone
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import func, select

from app.database import get_database
from app.crud import message_step as message_step_crud
from app.crud import chat as chat_crud
from app.schemas.trace import AgentTrace, TraceListItem, TraceListResponse
from app.schemas.chat import MessageStep
from app.services.trace_builder import build_trace_from_steps

logger = logging.getLogger(__name__)

api_router = APIRouter(prefix="/traces", tags=["traces"])


def utc_now():
    return datetime.now(timezone.utc)


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
):
    """List traces with pagination and time filtering.

    Returns TraceListResponse with pagination metadata.
    Default: first page, 10 items, last 24 hours.
    """
    try:
        db = get_database()
        async with db.session() as session:
            # Calculate time cutoff
            time_cutoff = utc_now() - timedelta(hours=hours)

            # Get total count matching the time filter
            count_stmt = select(func.count(chat_crud.Conversation.thread_id)).where(
                chat_crud.Conversation.updated_at >= time_cutoff,
                chat_crud.Conversation.is_deleted.is_(False),
            )
            count_result = await session.execute(count_stmt)
            total = count_result.scalar() or 0

            # Calculate pagination
            total_pages = (total + page_size - 1) // page_size if total > 0 else 0
            has_more = (page + 1) * page_size < total
            offset = page * page_size

            # Get conversations with time filter (most recent first)
            convs_stmt = (
                select(chat_crud.Conversation)
                .where(
                    chat_crud.Conversation.updated_at >= time_cutoff,
                    chat_crud.Conversation.is_deleted.is_(False),
                )
                .order_by(chat_crud.Conversation.updated_at.desc())
                .offset(offset)
                .limit(page_size)
            )

            convs_result = await session.execute(convs_stmt)
            convs = convs_result.scalars().all()

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

            # Get thread IDs for batch query
            thread_ids = [conv.thread_id for conv in convs]

            # Get trace stats for all threads in ONE query (GROUP BY) - avoids N+1
            stats_stmt = (
                select(
                    message_step_crud.MessageStepRecord.thread_id,
                    func.count(
                        func.distinct(message_step_crud.MessageStepRecord.session_id)
                    ).label("total_turns"),
                    func.coalesce(
                        func.sum(message_step_crud.MessageStepRecord.latency_ms), 0
                    ).label("total_latency_ms"),
                )
                .where(message_step_crud.MessageStepRecord.thread_id.in_(thread_ids))
                .group_by(message_step_crud.MessageStepRecord.thread_id)
            )

            stats_result = await session.execute(stats_stmt)
            stats_rows = stats_result.all()

            # Build lookup dict
            stats_lookup = {
                row.thread_id: {
                    "total_turns": row.total_turns,
                    "total_latency_ms": row.total_latency_ms,
                }
                for row in stats_rows
            }

            # Build items
            items = []
            for conv in convs:
                stats = stats_lookup.get(
                    conv.thread_id,
                    {
                        "total_turns": 0,
                        "total_latency_ms": 0,
                    },
                )
                items.append(
                    TraceListItem(
                        thread_id=conv.thread_id,
                        title=conv.title,
                        total_turns=stats["total_turns"],
                        total_latency_ms=stats["total_latency_ms"],
                        last_updated=conv.updated_at,
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


@api_router.get("/{thread_id}", response_model=AgentTrace)
async def get_trace(thread_id: UUID):
    """Get the full agent trace for a specific thread.

    Returns an AgentTrace with all turns, tool calls, and metadata.
    """
    try:
        db = get_database()
        async with db.session() as session:
            # Get conversation info
            conv = await chat_crud.read_conversation_by_thread_id(session, thread_id)
            if not conv:
                raise HTTPException(status_code=404, detail="Thread not found")

            # Get all message steps for this thread
            steps = await message_step_crud.get_steps_by_thread_id(session, thread_id)

            # Build trace from raw steps
            trace = build_trace_from_steps(
                thread_id=thread_id,
                steps=steps,
                title=conv.title or f"Conversation {thread_id}",
            )

            return trace

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting trace for thread {thread_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@api_router.get("/{thread_id}/turns/{session_id}/steps", response_model=list[MessageStep])
async def get_turn_steps(thread_id: UUID, session_id: UUID):
    """Get raw message steps for a specific turn (session).

    Returns the original message_steps records for DAG visualization.
    Each step includes: step_number, message_type, content, thinking, tool_calls, 
    tool_name, tool_args, tool_output, tool_call_id.
    """
    try:
        db = get_database()
        async with db.session() as db_session:
            # Verify thread exists
            conv = await chat_crud.read_conversation_by_thread_id(db_session, thread_id)
            if not conv:
                raise HTTPException(status_code=404, detail="Thread not found")

            # Get all steps for this thread
            all_steps = await message_step_crud.get_raw_steps_by_thread(db_session, thread_id)

            # Filter by session_id
            turn_steps = [step for step in all_steps if step.session_id == session_id]

            if not turn_steps:
                raise HTTPException(status_code=404, detail="Turn not found")

            # Convert to MessageStep schema
            steps = []
            for record in turn_steps:
                step = MessageStep(
                    session_id=record.session_id,
                    step_number=record.step_number,
                    message_type=record.message_type,
                    content=record.content,
                    thinking=record.thinking,
                    tool_calls=record.tool_calls,
                    tool_name=record.tool_name,
                    tool_args=record.tool_args,
                    tool_output=record.tool_output,
                    tool_call_id=record.tool_call_id,
                    model_name=record.model_name,
                    latency_ms=record.latency_ms,
                )
                steps.append(step)

            return steps

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting turn steps for thread {thread_id}, session {session_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
