import logging
from uuid import UUID
from fastapi import APIRouter, HTTPException, status, Depends, Query
from fastapi.responses import StreamingResponse, JSONResponse
from langchain_core.runnables import RunnableConfig
from langchain_core.messages import AIMessage, AnyMessage, ToolMessage
from langgraph.graph.state import CompiledStateGraph
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Any, List

from app.api.v1.dependencies import get_db
from app.schemas.chat import (
    ConversationCreate,
    ConversationInDB,
    ConversationUpdate,
    ChatMessage,
    UserInput,
    ChatHistory,
)
from app.schemas.title import TitleGenerateRequest, TitleGenerateResponse
from app.utils.agent_utils import get_agent
from app.utils.llm import is_thinking_mode_available
from app.core.config import settings
from app.core.model_manager import ModelManager
from app.utils.message_utils import (
    handle_input,
    langchain_to_chat_message,
    streaming_message_generator,
    collect_tool_calls_for_final_response,
)
from app.crud.chat import (
    read_conversation_by_thread_id,
    update_conversation_by_thread_id,
    list_conversations,
    create_conversation,
    soft_delete_conversation_by_thread_id,
)
from app.crud import message_step as message_step_crud


logger = logging.getLogger(__name__)

api_router = APIRouter(prefix="/chat", tags=["Chat"])


def _sse_response_example() -> dict[int | str, Any]:
    return {
        status.HTTP_200_OK: {
            "description": "Server Sent Event Response",
            "content": {
                "text/event-stream": {
                    "example": "data: {'type': 'token', 'content': 'Hello'}\n\ndata: {'type': 'token', 'content': ' World'}\n\ndata: [DONE]\n\n",
                    "schema": {"type": "string"},
                }
            },
        }
    }


@api_router.post(
    "/stream",
    response_class=StreamingResponse,
    responses=_sse_response_example(),
)
async def stream(user_input: UserInput) -> StreamingResponse:
    """
    Stream an agent's response to a user input, including intermediate messages and tokens.
    """
    agent_id = user_input.agent_id
    if not agent_id:
        raise HTTPException(status_code=400, detail="agent_id is not provided")

    logger.info(
        "stream endpoint called: agent_id=%s, thread_id=%s, thinking_mode=%s",
        agent_id,
        user_input.thread_id,
        user_input.thinking_mode,
    )

    agent: CompiledStateGraph = await get_agent(agent_id)
    return StreamingResponse(
        streaming_message_generator(user_input, agent),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@api_router.post("/invoke")
async def invoke(user_input: UserInput) -> ChatMessage:
    """Async invoke an agent with user input to retrieve a final response."""
    agent_id = user_input.agent_id
    if not agent_id:
        raise HTTPException(status_code=400, detail="agent_id is not provided")

    agent: CompiledStateGraph = await get_agent(agent_id)
    kwargs = await handle_input(user_input, agent)

    try:
        response_events: list[tuple[str, Any]] = await agent.ainvoke(
            **kwargs,
            stream_mode=["updates", "values"],  # type: ignore
        )
        response_type, response = response_events[-1]
        if response_type == "values":
            output = langchain_to_chat_message(response["messages"][-1])
        elif response_type == "updates" and "__interrupt__" in response:
            output = langchain_to_chat_message(
                AIMessage(content=response["__interrupt__"][0].value)
            )
        else:
            raise ValueError(f"Unexpected response type: {response_type}")

        return output
    except Exception as e:
        logger.error("An exception occurred: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="Unexpected error")


@api_router.get("/history/{agent_id}/{thread_id}")
async def history(
    agent_id: str,
    thread_id: UUID,
    db: AsyncSession = Depends(get_db),
) -> ChatHistory:
    """
    Get chat history with message sequence for sidebar.
    """
    if not agent_id:
        raise HTTPException(status_code=400, detail="agent_id is not provided")

    if not thread_id:
        return ChatHistory(messages=[], message_sequence=[])

    try:
        # Get message steps from database for sidebar
        message_sequence = await message_step_crud.get_message_steps_by_thread(
            db=db, thread_id=thread_id
        )

        # Get messages from checkpointer for main chat UI
        agent: CompiledStateGraph = await get_agent(agent_id)
        config = RunnableConfig({"configurable": {"thread_id": thread_id}})
        state_snapshot = await agent.aget_state(config=config)
        messages: list[AnyMessage] = state_snapshot.values.get("messages", [])

        # Build messages for main chat UI: only human and final AI messages
        chat_messages: list[ChatMessage] = []

        for i, msg in enumerate(messages):
            # Skip ToolMessage - not shown in main chat
            if isinstance(msg, ToolMessage):
                continue

            # For AIMessage: only include if it has content and no tool_calls
            if isinstance(msg, AIMessage):
                if msg.tool_calls:
                    continue
                if not msg.content or not str(msg.content).strip():
                    continue

            chat_message = langchain_to_chat_message(msg)

            # For final AI messages, collect tool info from preceding messages
            if isinstance(msg, AIMessage) and msg.content and str(msg.content).strip():
                tool_info = collect_tool_calls_for_final_response(messages, i)
                if tool_info:
                    chat_message.custom_data["tool_info"] = tool_info

            chat_messages.append(chat_message)

        return ChatHistory(messages=chat_messages, message_sequence=message_sequence)

    except Exception as e:
        logger.error("Error retrieving chat history: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="Unexpected error")


@api_router.get("/title/{thread_id}")
async def get_conversation_title(
    thread_id: UUID | None = None, db: AsyncSession = Depends(get_db)
) -> ConversationInDB | None:
    """Get the title of a conversation."""
    if not thread_id:
        raise HTTPException(status_code=400, detail="thread_id is not provided")

    try:
        conv = await read_conversation_by_thread_id(db=db, thread_id=thread_id)
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
    thread_id: UUID,
    conversation_title: ConversationUpdate,
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
            db=db, thread_id=thread_id, update_data=conversation_title
        )
        if conv is None:
            return None
        return ConversationInDB.model_validate(conv)
    except Exception as e:
        logger.error("Error setting conversation title: %s", e)
        raise HTTPException(status_code=500, detail="Error setting conversation title")


@api_router.get("/conversations")
async def get_conversations(
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
    """Get a list of recent conversations (most recently updated first)."""
    try:
        conversations, total = await list_conversations(
            db=db, limit=limit, offset=offset
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
    db: AsyncSession = Depends(get_db),
) -> ConversationInDB:
    """Create a conversation in DB."""
    try:
        conv = await create_conversation(db=db, conversation_in=conversation_in)
        return ConversationInDB.model_validate(conv)
    except Exception as e:
        logger.error("Error creating conversation: %s", e)
        raise HTTPException(status_code=500, detail="Error creating conversation")


@api_router.post("/title/generate", response_model=TitleGenerateResponse)
async def generate_title(request: TitleGenerateRequest) -> TitleGenerateResponse:
    """
    Generate a conversation title using the default LLM.

    Uses system/user message separation to prevent prompt injection.
    """
    try:
        model_id = ModelManager.get_default_llm_id()
        if not model_id:
            raise ValueError("No default LLM configured")

        router = await ModelManager.get_router()
        if not router:
            raise ValueError("Model router not initialized")

        # Use chat message format to isolate user input from system prompt (prevents prompt injection)
        # Truncate user input to limit injection surface
        truncated_user_msg = request.user_message[:200]

        if request.ai_response:
            messages = [
                {
                    "role": "system",
                    "content": (
                        "Based on the following conversation, generate a concise title "
                        "(max 20 characters, in the same language as the conversation). "
                        "Only output the title, nothing else."
                    ),
                },
                {
                    "role": "user",
                    "content": f"User: {truncated_user_msg}\nAI: {request.ai_response[:200]}",
                },
            ]
        else:
            messages = [
                {
                    "role": "system",
                    "content": (
                        "Generate a concise title (max 20 characters, in the same language) "
                        "for this message. Only output the title, nothing else."
                    ),
                },
                {
                    "role": "user",
                    "content": truncated_user_msg,
                },
            ]

        # Direct LiteLLM call (bypassing LangChain to avoid pydantic warnings)
        resp = await router.acompletion(
            model=model_id,
            messages=messages,  # type: ignore[arg-type]
        )

        content = resp.choices[0].message.content
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


@api_router.get("/thinking-mode")
async def get_thinking_mode_status() -> dict[str, bool]:
    """Check if thinking mode is available."""
    return {"available": is_thinking_mode_available()}


@api_router.delete("/conversations/{thread_id}", status_code=204)
async def delete_conversation(
    thread_id: UUID,
    db: AsyncSession = Depends(get_db),
) -> None:
    """Soft-delete a conversation by thread_id."""
    try:
        deleted = await soft_delete_conversation_by_thread_id(
            db=db, thread_id=thread_id
        )
        if not deleted:
            raise HTTPException(status_code=404, detail="Conversation not found")
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error deleting conversation %s: %s", thread_id, e)
        raise HTTPException(status_code=500, detail="Error deleting conversation")


@api_router.get("/models")
async def get_available_models() -> dict[str, Any]:
    """Get all available models from .env configuration."""
    models = settings.get_model_info_list()
    default_model = settings.LLM_DEFAULT_MODEL
    return {"models": models, "default_model": default_model}
