import logging
from uuid import UUID
from fastapi import APIRouter, HTTPException, status, Depends, Query
from fastapi.responses import StreamingResponse
from langchain_core.runnables import RunnableConfig
from langchain_core.messages import AIMessage, AnyMessage
from langgraph.graph.state import CompiledStateGraph
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Any, List

from app.database import adb_manager
from app.schemas.chat import ConversationCreate, ConversationInDB, ConversationUpdate
from app.utils.agent_utils import get_agent
from app.schemas.chat import ChatMessage, UserInput, ChatHistory
from app.utils.message_utils import (
    handle_input,
    langchain_to_chat_message,
    streaming_message_generator,
)
from app.crud.chat import (
    read_conversation_by_thread_id,
    update_conversation_by_thread_id,
    list_conversations,
    create_conversation,
)


logger = logging.getLogger(__name__)

api_router = APIRouter(prefix="/chat", tags=["Chat"])


async def get_db():
    """Dependency to provide async session"""
    async with adb_manager.session() as session:
        yield session


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

    Use thread_id to persist and continue a multi-turn conversation. run_id kwarg
    is also attached to all messages for recording feedback.

    Set `stream_tokens=false` to return intermediate messages but not token-by-token.
    """
    agent_id = user_input.agent_id
    if not agent_id:
        raise HTTPException(status_code=400, detail="agent_id is not provided")

    agent: CompiledStateGraph = await get_agent(agent_id)
    return StreamingResponse(
        streaming_message_generator(user_input, agent),
        media_type="text/event-stream",
    )


@api_router.post("/invoke")
async def invoke(user_input: UserInput) -> ChatMessage:
    """
    Async invoke an agent with user input to retrieve a final response.

    Use thread_id to persist and continue a multi-turn conversation.
    """

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
            # Normal response, the agent completed successfully
            output = langchain_to_chat_message(response["messages"][-1])
        elif response_type == "updates" and "__interrupt__" in response:
            # The last thing to occur was an interrupt
            # Return the value of the first interrupt as an AIMessage
            output = langchain_to_chat_message(
                AIMessage(content=response["__interrupt__"][0].value)
            )
        else:
            raise ValueError(f"Unexpected response type: {response_type}")

        return output
    except Exception as e:
        logger.error(f"An exception occurred: {e}")
        raise HTTPException(status_code=500, detail="Unexpected error")


@api_router.get("/history/{agent_id}/{thread_id}")
async def history(
    agent_id: str | None = None, thread_id: UUID | None = None
) -> ChatHistory:
    """
    Get chat history.
    """
    if not agent_id:
        raise HTTPException(status_code=400, detail="agent_id is not provided")

    if not thread_id:
        return ChatHistory(messages=[])
    agent: CompiledStateGraph = await get_agent(agent_id)
    config = RunnableConfig({"configurable": {"thread_id": thread_id}})
    try:
        state_snapshot = await agent.aget_state(config=config)
        messages: list[AnyMessage] = state_snapshot.values.get("messages", [])
        chat_messages: list[ChatMessage] = [
            langchain_to_chat_message(m) for m in messages
        ]
        return ChatHistory(messages=chat_messages)
    except Exception as e:
        logger.error(f"An exception occurred: {e}")
        raise HTTPException(status_code=500, detail="Unexpected error")


@api_router.get("/title/{thread_id}")
async def get_conversation_title(
    thread_id: UUID | None = None, db: AsyncSession = Depends(get_db)
) -> ConversationInDB | None:
    """Get the title of a conversation.

    Args:
        thread_id: The thread ID of the conversation

    Returns:
        Dictionary containing the conversation title
    """
    if not thread_id:
        raise HTTPException(status_code=400, detail="thread_id is not provided")

    try:
        return await read_conversation_by_thread_id(db=db, thread_id=thread_id)
    except Exception as e:
        logger.error(f"Error retrieving conversation title for thread {thread_id}: {e}")
        raise HTTPException(
            status_code=500, detail=f"Error retrieving conversation title: {str(e)}"
        )


@api_router.post("/title")
async def update_conversation_title(
    conversation_title: ConversationUpdate, db: AsyncSession = Depends(get_db)
) -> ConversationInDB | None:
    """
    Set or update the title of a conversation.
    """
    thread_id = conversation_title.thread_id
    title = conversation_title.title.strip()

    if not thread_id:
        raise HTTPException(
            status_code=400, detail="thread_id is required to set conversation title."
        )
    if not title:
        raise HTTPException(
            status_code=400, detail="title is required to set conversation title."
        )

    try:
        return await update_conversation_by_thread_id(
            db=db, update_data=conversation_title
        )
    except Exception as e:
        logger.error(f"Error setting conversation title: {e}")
        raise HTTPException(
            status_code=500, detail=f"Error setting conversation title: {str(e)}"
        )


@api_router.get("/conversations", response_model=List[ConversationInDB])
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
) -> List[ConversationInDB]:
    """
    Get a list of recent conversations (most recently updated first).

    Returns a paginated list of conversations that are not deleted.
    """
    try:
        conversations, _ = await list_conversations(db=db, limit=limit, offset=offset)

        return conversations

    except Exception as e:
        logger.error(f"Error retrieving conversations: {e}")
        raise HTTPException(
            status_code=500, detail=f"Error retrieving conversations: {str(e)}"
        )


@api_router.post("/conversations", response_model=ConversationInDB)
async def save_conversation(
    conversation_in: ConversationCreate,
    db: AsyncSession = Depends(get_db),
) -> ConversationInDB:
    """
    Create a conversation in DB.
    """
    try:
        return await create_conversation(db=db, conversation_in=conversation_in)
    except Exception as e:
        logger.error(f"Error creating conversation: {e}")
        raise HTTPException(
            status_code=500, detail=f"Error creating conversation: {str(e)}"
        )
