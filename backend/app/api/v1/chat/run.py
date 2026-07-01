"""Agent run endpoints — invoke and streaming.

Routes:
    POST /chat/{thread_id}/invoke  — One-shot (non-streaming) agent response
    POST /chat/{thread_id}/stream  — SSE streaming agent response

Invoke logic uses ChatService for business logic coordination.
Streaming logic uses ChatStreamingService from app.utils.sse.

Authentication required for all endpoints. User ID is extracted from JWT token.
``thread_id`` is a path parameter. ``request_id`` is extracted from the
``X-Request-ID`` header (auto-generated if not provided).
"""

import logging
import uuid
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Header, status
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


@api_router.post("/{thread_id}/invoke")
async def invoke(
    thread_id: UUID,
    user: CurrentUser,
    user_input: UserInput,
    db: DBSession,
    x_request_id: str | None = Header(default=None, alias="X-Request-ID"),
) -> ChatMessage:
    """Async invoke the supervisor agent with user input to retrieve a final response.

    After the agent returns, token usage is accumulated across all AI
    messages and persisted to the conversation, and the execution DAG
    is snapshot to ``trace_executions`` for offline trace viewing.

    Business logic is delegated to ChatService.invoke().

    Authentication required. User ID from JWT token.
    """
    request_id = x_request_id or str(uuid.uuid4())

    supervisor = get_agent()
    service = ChatService(supervisor)
    return await service.invoke(db, user_input, thread_id, user.id, request_id)


@api_router.post(
    "/{thread_id}/stream",
    response_class=StreamingResponse,
    responses=_sse_response_example(),
)
async def stream(
    thread_id: UUID,
    user: CurrentUser,
    user_input: UserInput,
    x_request_id: str | None = Header(default=None, alias="X-Request-ID"),
) -> StreamingResponse:
    """Stream the supervisor agent's response, including intermediate messages and tokens.

    Business logic is delegated to ChatStreamingService.generate().

    Authentication required. User ID from JWT token.
    """
    request_id = x_request_id or str(uuid.uuid4())

    logger.info(
        "stream endpoint called: thinking_mode=%s",
        user_input.thinking_mode,
    )

    supervisor = get_agent()
    service = ChatStreamingService(supervisor)

    return StreamingResponse(
        service.generate(user_input, thread_id, user.id, request_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
