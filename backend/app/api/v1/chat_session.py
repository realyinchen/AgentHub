"""Chat session endpoints — conversation CRUD, statistics, and thinking-mode status.

Routes:
    GET    /chat/conversations              — List conversations (paginated, user-scoped)
    POST   /chat/conversations              — Create a conversation
    DELETE /chat/conversations/{thread_id}  — Soft-delete a conversation
    GET    /chat/stats/daily                — Daily conversation + token stats
    GET    /chat/thinking-mode              — Thinking-mode availability status
"""

import logging
from uuid import UUID

from fastapi import APIRouter, HTTPException, Depends, Query
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.dependencies import get_db
from app.schemas.chat import ConversationCreate, ConversationInDB
from app.infra.llm import ModelManager
from app.crud.chat import (
    list_conversations,
    create_conversation,
    soft_delete_conversation_by_thread_id,
    get_daily_conversation_stats,
)


logger = logging.getLogger(__name__)

api_router = APIRouter(prefix="/chat", tags=["Chat"])


@api_router.get("/conversations")
async def get_conversations(
    user_id: str = Query(..., description="User ID to scope conversations"),
    limit: int = Query(
        20,
        ge=1,
        le=100,
        description="Maximum number of conversations to retrieve (1-100)",
    ),
    offset: int = Query(
        0, ge=0, description="Number of conversations to skip (for pagination)"
    ),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Get a list of recent conversations for a user (most recently updated first)."""
    try:
        conversations, total = await list_conversations(
            db=db, user_id=user_id, limit=limit, offset=offset
        )

        response = JSONResponse(
            content=[
                ConversationInDB.model_validate(conv).model_dump(mode="json")
                for conv in conversations
            ],
            headers={"X-Total-Count": str(total)},
        )
        return response  # type: ignore

    except Exception as e:
        logger.error("Error retrieving conversations: %s", e)
        raise HTTPException(status_code=500, detail="Error retrieving conversations")


@api_router.post("/conversations", response_model=ConversationInDB)
async def save_conversation(
    conversation_in: ConversationCreate,
    user_id: str = Query(..., description="User ID who owns this conversation"),
    db: AsyncSession = Depends(get_db),
) -> ConversationInDB:
    """Create a conversation in DB."""
    try:
        conv = await create_conversation(
            db=db, conversation_in=conversation_in, user_id=user_id
        )
        return ConversationInDB.model_validate(conv)
    except Exception as e:
        logger.error("Error creating conversation: %s", e)
        raise HTTPException(status_code=500, detail="Error creating conversation")


@api_router.delete("/conversations/{thread_id}", status_code=204)
async def delete_conversation(
    thread_id: UUID,
    user_id: str = Query(..., description="User ID who owns this conversation"),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Soft-delete a conversation by thread_id."""
    try:
        deleted = await soft_delete_conversation_by_thread_id(
            db=db, thread_id=thread_id, user_id=user_id
        )
        if not deleted:
            raise HTTPException(status_code=404, detail="Conversation not found")
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error deleting conversation %s: %s", thread_id, e)
        raise HTTPException(status_code=500, detail="Error deleting conversation")


@api_router.get("/stats/daily")
async def get_daily_stats(
    days: int = Query(
        30,
        ge=1,
        le=365,
        description="Number of days to retrieve statistics for (1-365)",
    ),
    user_id: str | None = Query(None, description="Optional user scope filter"),
    db: AsyncSession = Depends(get_db),
) -> list[dict[str, int | str]]:
    """Get daily conversation count and token usage statistics."""
    try:
        stats = await get_daily_conversation_stats(db=db, days=days, user_id=user_id)
        return stats
    except Exception as e:
        logger.error("Error retrieving daily statistics: %s", e)
        raise HTTPException(status_code=500, detail="Error retrieving daily statistics")


@api_router.get("/thinking-mode")
async def get_thinking_mode_status() -> dict[str, bool]:
    """Check if thinking mode is available."""
    return {"available": ModelManager.is_thinking_mode_available()}