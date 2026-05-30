"""Chat statistics endpoints — daily aggregate and per-conversation token stats.

Routes (under parent prefix /chat):
    GET /stats/daily                       — Daily conversation + token aggregate stats
    GET /conversations/{thread_id}/stats   — Per-conversation cumulative token stats
"""

from __future__ import annotations

import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.dependencies import get_db
from app.crud.chat import (
    get_daily_conversation_stats,
    read_conversation_by_thread_id,
)
from app.schemas.chat import (
    ConversationInDB,
    DailyStatsItem,
)

logger = logging.getLogger(__name__)

api_router = APIRouter(tags=["Chat"])


@api_router.get("/stats/daily", response_model=list[DailyStatsItem])
async def get_daily_stats(
    days: int = Query(
        30,
        ge=1,
        le=365,
        description="Number of days to retrieve statistics for (1-365)",
    ),
    user_id: str | None = Query(None, description="Optional user scope filter"),
    db: AsyncSession = Depends(get_db),
) -> list[DailyStatsItem]:
    """Get daily conversation count and token usage statistics."""
    stats = await get_daily_conversation_stats(db=db, days=days, user_id=user_id)
    return [DailyStatsItem(**s) for s in stats]


@api_router.get(
    "/conversations/{thread_id}/stats",
    response_model=ConversationInDB,
)
async def get_conversation_stats(
    thread_id: UUID,
    user_id: str = Query(..., description="User ID who owns this conversation"),
    db: AsyncSession = Depends(get_db),
) -> ConversationInDB:
    """Get cumulative token usage statistics for a specific conversation.

    Returns the full ConversationInDB object which includes all token
    fields (input_tokens, cache_read, output_tokens, reasoning, total_tokens).
    """
    conv = await read_conversation_by_thread_id(
        db=db, thread_id=thread_id, user_id=user_id
    )
    if conv is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return ConversationInDB.model_validate(conv)