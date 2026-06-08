"""Agent run endpoints — invoke and streaming.

Routes:
    POST /chat/invoke  — One-shot (non-streaming) agent response
    POST /chat/stream  — SSE streaming agent response

Invoke logic uses ChatService for business logic coordination.
Streaming logic uses ChatStreamingService from app.utils.sse.

Authentication required for all endpoints. User ID is extracted from JWT token
and injected into UserInput to ensure proper authorization and audit trail.
"""

import logging
from typing import Any

from fastapi import APIRouter, status
from fastapi.responses import StreamingResponse

from app.agents import get_agent
from app.api.v1.dependencies import DBSession
from app.infra.auth import CurrentUser
from app.schemas.chat import ChatMessage, UserInput
from app.services import ChatService, ChatStreamingService

logger = logging.getLogger(__name__)

api_router = APIRouter(tags=["Chat"])


def _sse_response_example() -> dict[int | str, Any]:
    return {
        status.HTTP_200_OK: {
            "description": "Server Sent Event Response",
            "content": {
                "text/event-stream": {
                    "example": (
                        "data: {'type': 'token', 'content': 'Hello'}\n\n"
                        "data: {'type': 'token', 'content': ' World'}\n\n"
                        "data: [DONE]\n\n"
                    ),
                    "schema": {"type": "string"},
                }
            },
        }
    }


@api_router.post("/invoke")
async def invoke(user: CurrentUser, user_input: UserInput, db: DBSession) -> ChatMessage:
    """Async invoke the supervisor agent with user input to retrieve a final response.

    After the agent returns, token usage is accumulated across all AI
    messages and persisted to the conversation, and the execution DAG
    is snapshot to ``trace_executions`` for offline trace viewing.

    Business logic is delegated to ChatService.invoke().

    Authentication required. User ID from JWT token overrides user_input.user_id
    to ensure proper authorization.
    """
    # Override user_id with authenticated user's ID for security
    user_input.user_id = user.id

    supervisor = get_agent()
    service = ChatService(supervisor)
    return await service.invoke(db, user_input)


@api_router.post(
    "/stream",
    response_class=StreamingResponse,
    responses=_sse_response_example(),
)
async def stream(user: CurrentUser, user_input: UserInput) -> StreamingResponse:
    """Stream the supervisor agent's response, including intermediate messages and tokens.

    Business logic is delegated to ChatStreamingService.generate().

    Authentication required. User ID from JWT token overrides user_input.user_id
    to ensure proper authorization.
    """
    # Override user_id with authenticated user's ID for security
    user_input.user_id = user.id

    logger.info(
        "stream endpoint called: thread_id=%s, thinking_mode=%s, user_id=%s",
        user_input.thread_id,
        user_input.thinking_mode,
        user.id,
    )

    supervisor = get_agent()
    service = ChatStreamingService(supervisor)

    return StreamingResponse(
        service.generate(user_input),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
