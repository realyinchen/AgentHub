"""Chat title endpoints — CRUD and auto-generation.

Routes:
    GET  /chat/title/{thread_id}   — Get conversation title
    POST /chat/title               — Set/update conversation title
    POST /chat/title/generate      — Auto-generate title via LLM
"""

import logging
from uuid import UUID

from fastapi import APIRouter, HTTPException, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.dependencies import get_db
from app.schemas.chat import ConversationInDB, ConversationUpdate, TitleGenerateRequest, TitleGenerateResponse
from langchain_core.messages import SystemMessage, HumanMessage

from app.crud.chat import (
    read_conversation_by_thread_id,
    update_conversation_by_thread_id,
)
from app.infra.llm.system import get_system_default_llm


logger = logging.getLogger(__name__)

api_router = APIRouter(prefix="/chat", tags=["Chat"])


@api_router.get("/title/{thread_id}")
async def get_conversation_title(
    thread_id: UUID,
    user_id: str = Query(..., description="User ID who owns this conversation"),
    db: AsyncSession = Depends(get_db),
) -> ConversationInDB | None:
    """Get the title of a conversation."""
    if not thread_id:
        raise HTTPException(status_code=400, detail="thread_id is not provided")

    try:
        conv = await read_conversation_by_thread_id(
            db=db, thread_id=thread_id, user_id=user_id
        )
        if conv is None:
            return None
        return ConversationInDB.model_validate(conv)
    except Exception as e:
        logger.error(
            "Error retrieving conversation title for thread %s: %s", thread_id, e
        )
        raise HTTPException(
            status_code=500, detail="Error retrieving conversation title"
        )


@api_router.post("/title")
async def update_conversation_title(
    conversation_title: ConversationUpdate,
    thread_id: UUID = Query(..., description="Thread ID of the conversation"),
    user_id: str = Query(..., description="User ID who owns this conversation"),
    db: AsyncSession = Depends(get_db),
) -> ConversationInDB | None:
    """Set or update the title of a conversation."""
    if not thread_id:
        raise HTTPException(
            status_code=400, detail="thread_id is required to set conversation title."
        )
    title = conversation_title.title
    if not title or not title.strip():
        raise HTTPException(
            status_code=400, detail="title is required to set conversation title."
        )

    try:
        conv = await update_conversation_by_thread_id(
            db=db, thread_id=thread_id, update_data=conversation_title, user_id=user_id
        )
        if conv is None:
            return None
        return ConversationInDB.model_validate(conv)
    except Exception as e:
        logger.error("Error setting conversation title: %s", e)
        raise HTTPException(status_code=500, detail="Error setting conversation title")


@api_router.post("/title/generate", response_model=TitleGenerateResponse)
async def generate_title(request: TitleGenerateRequest) -> TitleGenerateResponse:
    """Generate a conversation title using the system default LLM.

    Uses LangChain message types (SystemMessage / HumanMessage) for unified
    LLM invocation — consistent with all other LLM calls in the platform.
    System/user message separation prevents prompt injection.
    """
    try:
        llm = get_system_default_llm()

        # Truncate user input to limit injection surface
        truncated_user_msg = request.user_message[:200]

        if request.ai_response:
            messages = [
                SystemMessage(
                    content=(
                        "Based on the following conversation, generate a concise title "
                        "(max 20 characters, in the same language as the conversation). "
                        "Only output the title, nothing else."
                    )
                ),
                HumanMessage(
                    content=f"User: {truncated_user_msg}\nAI: {request.ai_response[:200]}"
                ),
            ]
        else:
            messages = [
                SystemMessage(
                    content=(
                        "Generate a concise title (max 20 characters, in the same language) "
                        "for this message. Only output the title, nothing else."
                    )
                ),
                HumanMessage(content=truncated_user_msg),
            ]

        # Unified LLM invocation via LangChain (appears in LangSmith traces)
        resp = await llm.ainvoke(messages)

        content = resp.content
        if not isinstance(content, str):
            content = str(content) if content else ""
        title = content.strip() if content else ""
        if title.startswith('"') and title.endswith('"'):
            title = title[1:-1]
        elif title.startswith("'") and title.endswith("'"):
            title = title[1:-1]
        if len(title) > 50:
            title = title[:47] + "..."

        return TitleGenerateResponse(title=title)

    except Exception as e:
        logger.error("Error generating title: %s", e)
        fallback = request.user_message[:30]
        if len(request.user_message) > 30:
            fallback += "..."
        return TitleGenerateResponse(title=fallback)