"""Chat history endpoint — message history with step sequence.

Route (under parent prefix /chat):
    GET /history/{thread_id}  — Conversation history + step sequence for sidebar
"""

import logging
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.dependencies import get_db
from app.crud import trace as trace_crud
from app.crud.chat import read_conversation_by_thread_id
from app.schemas.chat import ChatHistory
from app.services.conversation.journal_chat_projection import (
    project_journal_chat_messages,
)
from app.services.conversation.journal_repository import (
    ConversationEventRepository,
)
from app.schemas.trace import StepOutput

logger = logging.getLogger(__name__)

api_router = APIRouter(tags=["Chat"])


@api_router.get("/history/{thread_id}")
async def history(
    thread_id: UUID,
    user_id: UUID = Query(..., description="User ID for ownership verification"),
    db: AsyncSession = Depends(get_db),
) -> ChatHistory:
    """Get chat history with message sequence for sidebar.

    Requires user_id to verify the conversation belongs to the requesting user.
    Returns empty history if the conversation does not belong to the user.
    """
    if not thread_id:
        return ChatHistory(messages=[], message_sequence=[])

    # Verify conversation ownership — prevent cross-user data leakage
    conversation = await read_conversation_by_thread_id(db, thread_id, user_id)
    if conversation is None:
        logger.warning(
            "History access denied: thread_id=%s does not belong to user_id=%s",
            thread_id,
            user_id,
        )
        return ChatHistory(messages=[], message_sequence=[])

    # Get message steps from persisted DAG for sidebar (no graph needed)
    _, steps, _ = await trace_crud.get_latest_dag_and_steps(db, thread_id)
    message_sequence: list[StepOutput] = [StepOutput(**s) for s in (steps or [])]

    journal_page = await ConversationEventRepository().list_events(
        db,
        user_id=user_id,
        thread_id=thread_id,
        limit=500,
    )
    if journal_page.events:
        return ChatHistory(
            messages=project_journal_chat_messages(journal_page.events),
            message_sequence=message_sequence,
        )

    return ChatHistory(
        messages=[],
        message_sequence=message_sequence,
    )
