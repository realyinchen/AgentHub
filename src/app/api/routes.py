# pyright: reportAssignmentType=false
import logging
from fastapi import APIRouter, HTTPException, status
from fastapi.responses import StreamingResponse
from langchain_core.runnables import RunnableConfig
from langchain.messages import AnyMessage
from typing import Any

from app.agents import rag_agent
from app.schema import ChatMessage, UserInput, ChatHistoryInput, ChatHistory
from app.utils.message_utils import (
    handle_input,
    langchain_to_chat_message,
    streaming_message_generator,
)

logger = logging.getLogger(__name__)

api_router = APIRouter()


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
    "/stream", response_class=StreamingResponse, responses=_sse_response_example()
)
async def stream(user_input: UserInput) -> StreamingResponse:
    """
    Stream an agent's response to a user input, including intermediate messages and tokens.

    If agent_id is not provided, the default agent will be used.
    Use thread_id to persist and continue a multi-turn conversation. run_id kwarg
    is also attached to all messages for recording feedback.
    Use user_id to persist and continue a conversation across multiple threads.

    Set `stream_tokens=false` to return intermediate messages but not token-by-token.
    """
    return StreamingResponse(
        streaming_message_generator(user_input, rag_agent),
        media_type="text/event-stream",
    )


@api_router.post("/invoke")
async def invoke(user_input: UserInput) -> ChatMessage:
    """
    Async invoke an agent with user input to retrieve a final response.

    Use thread_id to persist and continue a multi-turn conversation.
    """

    kwargs = await handle_input(user_input)

    try:
        response = await rag_agent.ainvoke(**kwargs)  # type: ignore
        # Normal response, the agent completed successfully
        output = langchain_to_chat_message(response["messages"][-1])
        return output
    except Exception as e:
        logger.error(f"An exception occurred: {e}")
        raise HTTPException(status_code=500, detail="Unexpected error")


@api_router.post("/history")
async def history(input: ChatHistoryInput) -> ChatHistory:
    """
    Get chat history.
    """

    config = RunnableConfig({"configurable": {"thread_id": input.thread_id}})
    try:
        state_snapshot = await rag_agent.aget_state(config=config)
        messages: list[AnyMessage] = state_snapshot.values["messages"]
        chat_messages: list[ChatMessage] = [
            langchain_to_chat_message(m) for m in messages
        ]
        return ChatHistory(messages=chat_messages)
    except Exception as e:
        logger.error(f"An exception occurred: {e}")
        raise HTTPException(status_code=500, detail="Unexpected error")
