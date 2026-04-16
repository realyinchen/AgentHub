import logging
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
) -> MessageStepRecord:
    """Save a tool execution step to the database.
    
    This combines tool call and result into a single step.
    """
    record = MessageStepRecord(
        thread_id=thread_id,
        session_id=session_id,
        step_number=step_number,
        message_type="tool",
        tool_name=tool_name,
        tool_args=tool_args or {},
        tool_output=tool_output,
    )
    db.add(record)
    await db.flush()
    await db.refresh(record)
    logger.debug(f"Saved tool step {step_number}: {tool_name} for thread {thread_id}, session {session_id}")
    return record


async def save_ai_step(
    db: AsyncSession,
    thread_id: UUID,
    session_id: UUID,
    step_number: int,
    content: str | None = None,
    thinking: str | None = None,
) -> MessageStepRecord:
    """Save an AI response step to the database.
    
    This is called when the agent completes its response.
    """
    record = MessageStepRecord(
        thread_id=thread_id,
        session_id=session_id,
        step_number=step_number,
        message_type="ai",
        content=content,
        thinking=thinking,
    )
    db.add(record)
    await db.flush()
    await db.refresh(record)
    logger.debug(f"Saved ai step {step_number} for thread {thread_id}, session {session_id}")
    return record


async def get_message_steps_by_thread(
    db: AsyncSession,
    thread_id: UUID,
) -> List[MessageStep]:
    """Get all message steps for a thread, ordered by step_number.
    
    Returns a list of MessageStep schema objects for the API response.
    """
    stmt = select(MessageStepRecord).where(
        MessageStepRecord.thread_id == thread_id,
    ).order_by(MessageStepRecord.step_number.asc())
    
    result = await db.execute(stmt)
    records = result.scalars().all()
    
    steps = []
    for record in records:
        step = MessageStep(
            session_id=record.session_id,  # type: ignore[arg-type]
            step_number=record.step_number,  # type: ignore[arg-type]
            message_type=record.message_type,  # type: ignore[arg-type]
            content=record.content,  # type: ignore[arg-type]
            thinking=record.thinking,  # type: ignore[arg-type]
            tool_name=record.tool_name,  # type: ignore[arg-type]
            tool_args=record.tool_args,  # type: ignore[arg-type]
            tool_output=record.tool_output,  # type: ignore[arg-type]
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
    stmt = select(MessageStepRecord.step_number).where(
        MessageStepRecord.thread_id == thread_id,
    ).order_by(MessageStepRecord.step_number.desc()).limit(1)
    
    result = await db.execute(stmt)
    max_step = result.scalar_one_or_none()
    
    return max_step or 0


async def get_max_step_number_for_session(
    db: AsyncSession,
    thread_id: UUID,
    session_id: UUID,
) -> int:
    """Get the maximum step number for a specific session within a thread.
    
    This allows each session to have its own step numbering starting from 1.
    Returns 0 if no steps exist for this session.
    """
    stmt = select(MessageStepRecord.step_number).where(
        MessageStepRecord.thread_id == thread_id,
        MessageStepRecord.session_id == session_id,
    ).order_by(MessageStepRecord.step_number.desc()).limit(1)
    
    result = await db.execute(stmt)
    max_step = result.scalar_one_or_none()
    
    return max_step or 0
