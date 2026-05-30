"""Conversation CRUD, title, and thinking-mode endpoints.

Routes (all under parent prefix /chat):
    GET    /conversations                         — List conversations (paginated, user-scoped)
    POST   /conversations                         — Create a conversation
    DELETE /conversations/{thread_id}             — Soft-delete a conversation
    GET    /conversations/{id}/info               — Last-used model for a conversation
    GET    /conversations/{id}/title              — Get conversation title
    PATCH  /conversations/{id}/title              — Set/update conversation title
    POST   /conversations/{id}/title/generate     — Auto-generate title via LLM
    GET    /thinking-mode                         — Thinking-mode availability status
"""

from __future__ import annotations

import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from langchain_core.messages import HumanMessage, SystemMessage
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.dependencies import get_db
from app.crud.chat import (
    create_conversation,
    list_conversations,
    read_conversation_by_thread_id,
    soft_delete_conversation_by_thread_id,
    update_conversation_by_thread_id,
    get_latest_model_name,
)
from app.infra.llm.model_manager import get_model_manager
from app.infra.llm.system import get_system_default_llm
from app.schemas.chat import (
    ConversationCreate,
    ConversationInDB,
    ConversationInfoResponse,
    ConversationUpdate,
    ThinkingModeStatus,
    TitleGenerateRequest,
    TitleGenerateResponse,
)

logger = logging.getLogger(__name__)

api_router = APIRouter(tags=["Chat"])


# ── Conversation CRUD ─────────────────────────────────────────────────────────


@api_router.get("/conversations", response_model=list[ConversationInDB])
async def get_conversations(
    response: Response,
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
) -> list[ConversationInDB]:
    """Get a list of recent conversations for a user (most recently updated first)."""
    conversations, total = await list_conversations(
        db=db, user_id=user_id, limit=limit, offset=offset
    )
    response.headers["X-Total-Count"] = str(total)
    return [ConversationInDB.model_validate(c) for c in conversations]


@api_router.post("/conversations", response_model=ConversationInDB)
async def save_conversation(
    conversation_in: ConversationCreate,
    user_id: str = Query(..., description="User ID who owns this conversation"),
    db: AsyncSession = Depends(get_db),
) -> ConversationInDB:
    """Create a conversation in DB."""
    conv = await create_conversation(
        db=db, conversation_in=conversation_in, user_id=user_id
    )
    return ConversationInDB.model_validate(conv)


@api_router.delete("/conversations/{thread_id}", status_code=204)
async def delete_conversation(
    thread_id: UUID,
    user_id: str = Query(..., description="User ID who owns this conversation"),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Soft-delete a conversation by thread_id."""
    deleted = await soft_delete_conversation_by_thread_id(
        db=db, thread_id=thread_id, user_id=user_id
    )
    if not deleted:
        raise HTTPException(status_code=404, detail="Conversation not found")


# ── Conversation info ─────────────────────────────────────────────────────────


@api_router.get(
    "/conversations/{thread_id}/info", response_model=ConversationInfoResponse
)
async def get_conversation_info(
    thread_id: UUID,
    user_id: str = Query(..., description="User ID who owns this conversation"),
    db: AsyncSession = Depends(get_db),
) -> ConversationInfoResponse:
    """Get the last-used model for a conversation.

    Used when entering a historical conversation. Returns the model_name
    from the most recent trace execution. If the model is no longer
    active, falls back to the system default.
    """
    # Verify the conversation belongs to the user
    conv = await read_conversation_by_thread_id(
        db=db, thread_id=thread_id, user_id=user_id
    )
    if conv is None:
        raise HTTPException(status_code=404, detail="Conversation not found")

    model_name = await get_latest_model_name(db, thread_id)

    # Validate model is still active
    model_fallback = False
    if model_name:
        manager = get_model_manager()
        if not manager.is_model_active(model_name):
            model_name = (
                manager.get_default_llm_id() or manager.get_first_active_llm_id()
            )
            model_fallback = True
    else:
        manager = get_model_manager()
        model_name = (
            manager.get_default_llm_id() or manager.get_first_active_llm_id()
        )

    return ConversationInfoResponse(
        model_name=model_name,
        model_fallback=model_fallback,
    )


# ── Title CRUD ────────────────────────────────────────────────────────────────


@api_router.get("/conversations/{thread_id}/title")
async def get_conversation_title(
    thread_id: UUID,
    user_id: str = Query(..., description="User ID who owns this conversation"),
    db: AsyncSession = Depends(get_db),
) -> ConversationInDB | None:
    """Get the title of a conversation."""
    if not thread_id:
        raise HTTPException(status_code=400, detail="thread_id is not provided")

    conv = await read_conversation_by_thread_id(
        db=db, thread_id=thread_id, user_id=user_id
    )
    if conv is None:
        return None
    return ConversationInDB.model_validate(conv)


@api_router.patch("/conversations/{thread_id}/title")
async def update_conversation_title(
    thread_id: UUID,
    conversation_title: ConversationUpdate,
    user_id: str = Query(..., description="User ID who owns this conversation"),
    db: AsyncSession = Depends(get_db),
) -> ConversationInDB | None:
    """Set or update the title of a conversation (partial update via PATCH)."""
    if not thread_id:
        raise HTTPException(
            status_code=400, detail="thread_id is required to set conversation title."
        )
    title = conversation_title.title
    if not title or not title.strip():
        raise HTTPException(
            status_code=400, detail="title is required to set conversation title."
        )

    conv = await update_conversation_by_thread_id(
        db=db, thread_id=thread_id, update_data=conversation_title, user_id=user_id
    )
    if conv is None:
        return None
    return ConversationInDB.model_validate(conv)


@api_router.post(
    "/conversations/{thread_id}/title/generate",
    response_model=TitleGenerateResponse,
)
async def generate_title(
    thread_id: UUID,
    request: TitleGenerateRequest,
) -> TitleGenerateResponse:
    """Generate a conversation title using the system default LLM.

    Uses LangChain message types (SystemMessage / HumanMessage) for unified
    LLM invocation — consistent with all other LLM calls in the platform.
    System/user message separation prevents prompt injection.

    On any failure, returns a truncated fallback title instead of raising
    an exception — this endpoint is called during conversation creation and
    should not block the user flow.
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


# ── Thinking mode ─────────────────────────────────────────────────────────────


@api_router.get("/thinking-mode", response_model=ThinkingModeStatus)
async def get_thinking_mode_status() -> ThinkingModeStatus:
    """Check if thinking mode is available."""
    return ThinkingModeStatus(
        available=get_model_manager().is_thinking_mode_available()
    )