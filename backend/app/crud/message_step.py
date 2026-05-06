import json
import logging
from datetime import datetime
from uuid import UUID
from typing import List

from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.message_step import MessageStepRecord
from app.schemas.chat import MessageStep

logger = logging.getLogger(__name__)


async def save_tool_step(
    db: AsyncSession,
    thread_id: UUID,
    session_id: UUID,
    step_number: int,
    tool_name: str,
    tool_args: dict | None = None,
    tool_output: str | None = None,
    tool_call_id: str | None = None,
    run_id: str | None = None,
    parent_run_id: str | None = None,
    latency_ms: int | None = None,
) -> MessageStepRecord:
    """Save a tool execution step to the database.

    This combines tool call and result into a single step.
    
    Note: tool_args is stored as JSON with ensure_ascii=False to preserve
    Chinese characters in their original form (not as \\uXXXX escapes).
    """
    # Convert tool_args to JSON string with ensure_ascii=False for proper Chinese display
    # SQLAlchemy JSON column will handle the serialization
    record = MessageStepRecord(
        thread_id=thread_id,
        session_id=session_id,
        step_number=step_number,
        message_type="tool",
        tool_name=tool_name,
        tool_args=tool_args or {},
        tool_output=tool_output,
        tool_call_id=tool_call_id,
        run_id=run_id,
        parent_run_id=parent_run_id,
        latency_ms=latency_ms,
    )
    db.add(record)
    await db.flush()
    await db.refresh(record)
    logger.debug(
        f"Saved tool step {step_number}: {tool_name} for thread {thread_id}, session {session_id}"
    )
    return record


async def save_ai_step(
    db: AsyncSession,
    thread_id: UUID,
    session_id: UUID,
    step_number: int,
    content: str | None = None,
    thinking: str | None = None,
    tool_calls: list | None = None,
    run_id: str | None = None,
    parent_run_id: str | None = None,
    latency_ms: int | None = None,
    model_name: str | None = None,
) -> MessageStepRecord:
    """Save an AI response step to the database.

    This is called when the agent completes its response.
    
    Note: tool_calls is stored as JSON with ensure_ascii=False to preserve
    Chinese characters in their original form (not as \\uXXXX escapes).
    """
    record = MessageStepRecord(
        thread_id=thread_id,
        session_id=session_id,
        step_number=step_number,
        message_type="ai",
        content=content,
        thinking=thinking,
        tool_calls=tool_calls,
        run_id=run_id,
        parent_run_id=parent_run_id,
        latency_ms=latency_ms,
        model_name=model_name,
    )
    db.add(record)
    await db.flush()
    await db.refresh(record)
    logger.debug(
        f"Saved ai step {step_number} for thread {thread_id}, session {session_id}"
    )
    return record


async def save_human_step(
    db: AsyncSession,
    thread_id: UUID,
    session_id: UUID,
    step_number: int,
    content: str,
) -> MessageStepRecord:
    """Save a user message step to the database.

    This is called when the agent starts processing a user message.
    """
    record = MessageStepRecord(
        thread_id=thread_id,
        session_id=session_id,
        step_number=step_number,
        message_type="human",
        content=content,
    )
    db.add(record)
    await db.flush()
    await db.refresh(record)
    logger.debug(
        f"Saved human step {step_number} for thread {thread_id}, session {session_id}"
    )
    return record


async def get_message_steps_by_thread(
    db: AsyncSession,
    thread_id: UUID,
) -> List[MessageStep]:
    """Get all message steps for a thread, ordered by session creation time and step_number.

    Ensures steps from the same session are grouped together, and sessions are ordered
    by their creation time (first step's created_at), then by step number within each session.
    """
    stmt = (
        select(MessageStepRecord)
        .where(
            MessageStepRecord.thread_id == thread_id,
        )
    )

    result = await db.execute(stmt)
    records = result.scalars().all()

    if not records:
        return []

    # Group records by session_id and sort sessions by creation time
    # 1. Calculate min created_at for each session
    session_times: dict[UUID, datetime] = {}
    for record in records:
        if (record.session_id not in session_times or 
            record.created_at < session_times[record.session_id]):
            session_times[record.session_id] = record.created_at

    # 2. Sort sessions by their creation time
    sorted_session_ids = sorted(session_times.keys(), key=lambda sid: session_times[sid])

    # 3. Build the final sorted list: sessions ordered by time, steps by step_number
    steps: List[MessageStep] = []
    for session_id in sorted_session_ids:
        session_records = [r for r in records if r.session_id == session_id]
        session_records.sort(key=lambda r: r.step_number)
        for record in session_records:
            step = MessageStep(
                session_id=record.session_id,
                step_number=record.step_number,
                message_type=record.message_type,
                content=record.content,
                thinking=record.thinking,
                tool_name=record.tool_name,
                tool_args=record.tool_args,
                tool_output=record.tool_output,
            )
            steps.append(step)

    return steps


async def delete_message_steps_by_thread(
    db: AsyncSession,
    thread_id: UUID,
) -> int:
    """Delete all message steps for a thread.

    This is useful when regenerating a response.
    Returns the number of deleted records.
    """
    stmt = delete(MessageStepRecord).where(
        MessageStepRecord.thread_id == thread_id,
    )
    result = await db.execute(stmt)
    await db.flush()
    return result.rowcount or 0  # type: ignore[attr-defined]


async def get_max_step_number(
    db: AsyncSession,
    thread_id: UUID,
) -> int:
    """Get the maximum step number for a thread.

    Returns 0 if no steps exist.
    """
    stmt = (
        select(MessageStepRecord.step_number)
        .where(
            MessageStepRecord.thread_id == thread_id,
        )
        .order_by(MessageStepRecord.step_number.desc())
        .limit(1)
    )

    result = await db.execute(stmt)
    max_step = result.scalar_one_or_none()

    return max_step or 0


async def get_raw_steps_by_thread(
    db: AsyncSession,
    thread_id: UUID,
) -> List[MessageStepRecord]:
    """Get all raw MessageStepRecord objects for a thread, ordered by session_id and step_number.

    Used by the trace builder to construct AgentTrace objects.
    """
    stmt = (
        select(MessageStepRecord)
        .where(MessageStepRecord.thread_id == thread_id)
        .order_by(
            MessageStepRecord.session_id.asc(),
            MessageStepRecord.step_number.asc(),
        )
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def get_steps_by_thread_id(
    db: AsyncSession,
    thread_id: UUID,
) -> List[MessageStepRecord]:
    """Get all MessageStepRecord objects for a thread, ordered by step_number.

    Used by the trace builder to construct AgentTrace objects.
    Alias for get_raw_steps_by_thread for API consistency.
    """
    return await get_raw_steps_by_thread(db, thread_id)


async def get_max_step_number_for_session(
    db: AsyncSession,
    thread_id: UUID,
    session_id: UUID,
) -> int:
    """Get the maximum step number for a specific session within a thread.

    This allows each session to have its own step numbering starting from 1.
    Returns 0 if no steps exist for this session.
    """
    stmt = (
        select(MessageStepRecord.step_number)
        .where(
            MessageStepRecord.thread_id == thread_id,
            MessageStepRecord.session_id == session_id,
        )
        .order_by(MessageStepRecord.step_number.desc())
        .limit(1)
    )

    result = await db.execute(stmt)
    max_step = result.scalar_one_or_none()

    return max_step or 0
